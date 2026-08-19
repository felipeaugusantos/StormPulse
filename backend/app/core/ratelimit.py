"""Lightweight Redis fixed-window rate limiter.

Applied to authentication endpoints to blunt brute-force and abuse. Fail-open:
if Redis is unavailable the request is allowed (availability over strictness at
this layer) and the failure is logged.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class RateLimiter:
    """Callable FastAPI dependency enforcing a fixed-window limit per client."""

    def __init__(self, *, max_requests: int, window_seconds: int, scope: str) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.scope = scope

    def _client_key(self, request: Request) -> str:
        client = request.client.host if request.client else "unknown"
        return f"ratelimit:{self.scope}:{client}"

    async def __call__(self, request: Request) -> None:
        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return

        key = self._client_key(request)
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
