"""Tests for RateLimiter — no real Redis needed, a tiny in-memory stub matches
the ``incr``/``expire`` surface the limiter actually calls.

Covers the trusted-proxy policy and key strategy from hardening ADR-0033:
direct access, a trusted proxy's `X-Forwarded-For`/`Forwarded`, an untrusted
proxy (ignored), a spoof attempt from a direct (non-proxy) client, multiple
clients sharing one proxy IP, authenticated (tenant+user+IP) vs anonymous
(IP-only) keying, and Redis unavailability (fail-open).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.ratelimit import RateLimiter, resolve_client_ip
from app.core.security import create_access_token


class _FakeRedis:
    """Minimal stand-in for redis.asyncio.Redis: incr + expire only."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        pass


class _BrokenRedis:
    async def incr(self, key: str) -> int:
        raise ConnectionError("redis is down")

    async def expire(self, key: str, seconds: int) -> None:
        raise ConnectionError("redis is down")


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "jwt_secret_key": "unit-test-secret-at-least-32-bytes!",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _request(
    redis: object,
    settings: Settings,
    *,
    client_ip: str = "1.2.3.4",
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=redis, settings=settings)),
        client=SimpleNamespace(host=client_ip),
        headers=headers or {},
    )


async def test_allows_requests_under_the_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    for _ in range(3):
        await limiter(_request(redis, settings))  # type: ignore[arg-type]


async def test_blocks_requests_over_the_limit_with_429() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    req = _request(redis, settings)
    await limiter(req)  # type: ignore[arg-type]
    await limiter(req)  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await limiter(req)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers  # type: ignore[operator]


async def test_limits_are_per_client() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    await limiter(_request(redis, settings, client_ip="1.1.1.1"))  # type: ignore[arg-type]
    # different client, own budget
    await limiter(_request(redis, settings, client_ip="2.2.2.2"))  # type: ignore[arg-type]


async def test_fails_open_when_redis_is_unavailable() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    settings = _settings()
    req = _request(_BrokenRedis(), settings)
    await limiter(req)  # type: ignore[arg-type]
    # would 429 here if not fail-open
    await limiter(req)  # type: ignore[arg-type]


async def test_allows_when_redis_client_is_missing() -> None:
    limiter = RateLimiter(max_requests=0, window_seconds=60, scope="test")
    settings = _settings()
    req = _request(None, settings)
    await limiter(req)  # type: ignore[arg-type]


# --- Trusted-proxy IP resolution (ADR-0033) --------------------------------


def test_direct_access_uses_the_tcp_peer_ip() -> None:
    settings = _settings()  # no trusted proxies configured
    req = _request(None, settings, client_ip="9.9.9.9")
    assert resolve_client_ip(req, settings) == "9.9.9.9"  # type: ignore[arg-type]


def test_trusted_proxy_x_forwarded_for_is_honored() -> None:
    settings = _settings(trusted_proxy_ips="10.0.0.5")
    req = _request(
        None,
        settings,
        client_ip="10.0.0.5",  # the reverse proxy itself
        headers={"x-forwarded-for": "203.0.113.7"},
    )
    assert resolve_client_ip(req, settings) == "203.0.113.7"  # type: ignore[arg-type]


def test_trusted_proxy_forwarded_header_is_honored() -> None:
    settings = _settings(trusted_proxy_ips="10.0.0.5")
    req = _request(
        None,
        settings,
        client_ip="10.0.0.5",
        headers={"forwarded": 'for="203.0.113.9:4711";proto=https'},
    )
    assert resolve_client_ip(req, settings) == "203.0.113.9"  # type: ignore[arg-type]


def test_untrusted_proxy_header_is_ignored() -> None:
    # Peer IP is NOT in the trusted list — X-Forwarded-For must be ignored
    # entirely, even though it's present and well-formed.
    settings = _settings(trusted_proxy_ips="10.0.0.5")
    req = _request(
        None,
        settings,
        client_ip="66.66.66.66",
        headers={"x-forwarded-for": "203.0.113.7"},
    )
    assert resolve_client_ip(req, settings) == "66.66.66.66"  # type: ignore[arg-type]


def test_spoof_attempt_from_a_direct_client_is_ignored() -> None:
    # No trusted proxy configured at all — a client connecting directly and
    # forging X-Forwarded-For to frame another IP must not be believed.
    settings = _settings()
    req = _request(
        None,
        settings,
        client_ip="66.66.66.66",
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    assert resolve_client_ip(req, settings) == "66.66.66.66"  # type: ignore[arg-type]


def test_only_the_rightmost_forwarded_hop_is_trusted() -> None:
    # A malicious upstream client can prepend arbitrary entries to
    # X-Forwarded-For before it ever reaches our trusted proxy — only the
    # entry OUR proxy itself appended (the rightmost one) is trustworthy.
    settings = _settings(trusted_proxy_ips="10.0.0.5")
    req = _request(
        None,
        settings,
        client_ip="10.0.0.5",
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},
    )
    assert resolve_client_ip(req, settings) == "203.0.113.7"  # type: ignore[arg-type]


def test_trusted_proxy_cidr_range() -> None:
    settings = _settings(trusted_proxy_ips="10.0.0.0/24")
    req = _request(
        None,
        settings,
        client_ip="10.0.0.42",
        headers={"x-forwarded-for": "203.0.113.7"},
    )
    assert resolve_client_ip(req, settings) == "203.0.113.7"  # type: ignore[arg-type]


async def test_multiple_clients_behind_the_same_trusted_proxy_get_own_budgets() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings(trusted_proxy_ips="10.0.0.5")
    req_a = _request(
        redis, settings, client_ip="10.0.0.5", headers={"x-forwarded-for": "203.0.113.1"}
    )
    req_b = _request(
        redis, settings, client_ip="10.0.0.5", headers={"x-forwarded-for": "203.0.113.2"}
    )
    await limiter(req_a)  # type: ignore[arg-type]
    await limiter(req_b)  # type: ignore[arg-type]  # own budget, not blocked by A


# --- Key strategy: anonymous (IP) vs authenticated (tenant+user+IP) --------


async def test_anonymous_requests_are_keyed_by_ip_only() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    req = _request(redis, settings, client_ip="5.5.5.5")
    await limiter(req)  # type: ignore[arg-type]
    with pytest.raises(HTTPException):
        await limiter(req)  # type: ignore[arg-type]


async def test_authenticated_requests_are_keyed_by_tenant_and_user_not_just_ip() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    tenant_a = "11111111-1111-1111-1111-111111111111"
    tenant_b = "22222222-2222-2222-2222-222222222222"
    token_user1 = create_access_token(
        "user-1", settings, extra_claims={"tenant_id": tenant_a, "role": "member"}
    )
    token_user2 = create_access_token(
        "user-2", settings, extra_claims={"tenant_id": tenant_b, "role": "member"}
    )
    # Same IP (e.g. behind the same NAT), two different authenticated users —
    # each gets its own budget instead of sharing one IP-keyed bucket.
    req1 = _request(
        redis, settings, client_ip="8.8.8.8", headers={"authorization": f"Bearer {token_user1}"}
    )
    req2 = _request(
        redis, settings, client_ip="8.8.8.8", headers={"authorization": f"Bearer {token_user2}"}
    )
    await limiter(req1)  # type: ignore[arg-type]
    await limiter(req2)  # type: ignore[arg-type]  # not blocked by user 1's budget


async def test_same_user_from_two_ips_is_still_rate_limited_independently() -> None:
    # This limiter's chosen key includes IP even when authenticated (ADR-0033):
    # a single leaked/shared token doesn't get one combined budget across
    # every address it's used from.
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    tenant_id = "11111111-1111-1111-1111-111111111111"
    token = create_access_token(
        "same-user", settings, extra_claims={"tenant_id": tenant_id, "role": "member"}
    )
    req_from_ip1 = _request(
        redis, settings, client_ip="8.8.8.8", headers={"authorization": f"Bearer {token}"}
    )
    req_from_ip2 = _request(
        redis, settings, client_ip="9.9.9.9", headers={"authorization": f"Bearer {token}"}
    )
    await limiter(req_from_ip1)  # type: ignore[arg-type]
    await limiter(req_from_ip2)  # type: ignore[arg-type]  # different IP, own budget


async def test_malformed_bearer_token_is_treated_as_anonymous_not_an_error() -> None:
    limiter = RateLimiter(max_requests=5, window_seconds=60, scope="test")
    redis = _FakeRedis()
    settings = _settings()
    req = _request(
        redis, settings, client_ip="4.4.4.4", headers={"authorization": "Bearer not-a-real-jwt"}
    )
    await limiter(req)  # type: ignore[arg-type]  # must not raise
