"""Lightweight Redis fixed-window rate limiter.

Applied to authentication and versioned API endpoints to blunt brute-force
and abuse. Fail-open: if Redis is unavailable the request is allowed
(availability over strictness at this layer) and the failure is logged. This
is a deliberate, documented trade-off, not an oversight — see ADR-0033.
"""

from __future__ import annotations

import ipaddress
import logging

from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.core.security import TokenError, decode_token

logger = logging.getLogger(__name__)


def resolve_client_ip(request: Request, settings: Settings) -> str:
    """The client IP this request should be rate-limited (and logged) under.

    Trusted-proxy policy (hardening ADR-0033): `Forwarded`/`X-Forwarded-For`
    are attacker-controlled on any request that didn't pass through a proxy
    we actually trust — honoring them unconditionally would let a client
    either dodge its own limit or frame another IP for it. Only when the
    *direct* TCP peer (`request.client.host`, which the client cannot forge)
    is itself in `settings.trusted_proxy_networks` do we read the forwarded
    header at all, and even then we take only the entry that proxy itself
    appended — the rightmost one — never anything further left, which is
    exactly the part the original client could have supplied.

    This assumes a single trusted-proxy hop (the common case: one reverse
    proxy/load balancer directly in front of the API). A chain of more than
    one trusted proxy is not supported — see ADR-0033's documented
    limitation.
    """
    peer = request.client.host if request.client else "unknown"
    if not settings.trusted_proxy_networks or peer == "unknown":
        return peer

    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_addr in network for network in settings.trusted_proxy_networks):
        return peer

    forwarded = request.headers.get("forwarded")
    if forwarded:
        # RFC 7239: comma-separated hops, each like `for=1.2.3.4;proto=https`.
        # Take the rightmost hop's `for=` value — the one our own trusted
        # proxy appended.
        last_hop = forwarded.split(",")[-1]
        for part in last_hop.split(";"):
            key, _, value = part.strip().partition("=")
            if key.strip().lower() == "for":
                candidate = value.strip().strip('"').removeprefix("[").split("]")[0]
                candidate = candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate
                if candidate:
                    return candidate

    xff = request.headers.get("x-forwarded-for")
    if xff:
        last_hop = xff.split(",")[-1].strip()
        if last_hop:
            return last_hop

    return peer


def _authenticated_identity(request: Request, settings: Settings) -> tuple[str, str] | None:
    """Best-effort ``(tenant_id, user_id)`` from a valid Bearer access token.

    Never raises — an absent, malformed or expired token just means this
    request is keyed as anonymous (see ``RateLimiter._client_key``), it does
    not affect whether the request is otherwise allowed. Full verification
    (including that the user still exists/is active) stays
    ``get_current_user``'s job; this only needs the two JWT claims, so it
    never touches the database.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[len("bearer ") :].strip()
    if not token:
        return None
    try:
        payload = decode_token(token, settings, expected_type="access")
    except TokenError:
        return None
    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    if not user_id or not tenant_id:
        return None
    return str(tenant_id), str(user_id)


class RateLimiter:
    """Callable FastAPI dependency enforcing a fixed-window limit per client.

    Key strategy (ADR-0033): anonymous requests are keyed by IP alone;
    authenticated requests (a valid access token present) are keyed by
    tenant+user, on top of IP — so one compromised/leaked token can't be
    used to exhaust another tenant's budget from a different address, while
    two different users behind the same NAT/proxy IP still get independent
    budgets. ``scope`` (e.g. ``"auth"``, ``"default"``, ``"public"``) keeps
    these limits from sharing a bucket with each other.
    """

    def __init__(self, *, max_requests: int, window_seconds: int, scope: str) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.scope = scope

    def _client_key(self, request: Request, settings: Settings) -> str:
        ip = resolve_client_ip(request, settings)
        identity = _authenticated_identity(request, settings)
        if identity is not None:
            tenant_id, user_id = identity
            return f"ratelimit:{self.scope}:user:{tenant_id}:{user_id}:{ip}"
        return f"ratelimit:{self.scope}:anon:{ip}"

    async def __call__(self, request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return

        settings: Settings = request.app.state.settings
        key = self._client_key(request, settings)
        try:
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, self.window_seconds)
        except Exception as exc:  # noqa: BLE001 - fail open on limiter errors
            logger.warning("rate limiter unavailable, allowing request", extra={"error": str(exc)})
            return

        if current > self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Muitas requisições. Tente novamente em instantes.",
                headers={"Retry-After": str(self.window_seconds)},
            )
