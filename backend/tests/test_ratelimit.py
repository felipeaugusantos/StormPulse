"""Tests for RateLimiter — no real Redis needed, a tiny in-memory stub matches
the ``incr``/``expire`` surface the limiter actually calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.ratelimit import RateLimiter


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


def _request(redis: object, client_ip: str = "1.2.3.4") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=redis)),
        client=SimpleNamespace(host=client_ip),
    )


async def test_allows_requests_under_the_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60, scope="test")
    redis = _FakeRedis()
    for _ in range(3):
        await limiter(_request(redis))  # type: ignore[arg-type]


async def test_blocks_requests_over_the_limit_with_429() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=60, scope="test")
    redis = _FakeRedis()
    req = _request(redis)
    await limiter(req)  # type: ignore[arg-type]
    await limiter(req)  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        await limiter(req)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers  # type: ignore[operator]


async def test_limits_are_per_client() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    redis = _FakeRedis()
    await limiter(_request(redis, "1.1.1.1"))  # type: ignore[arg-type]
    # different client, own budget
    await limiter(_request(redis, "2.2.2.2"))  # type: ignore[arg-type]


async def test_fails_open_when_redis_is_unavailable() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60, scope="test")
    req = _request(_BrokenRedis())
    await limiter(req)  # type: ignore[arg-type]
    # would 429 here if not fail-open
    await limiter(req)  # type: ignore[arg-type]


async def test_allows_when_redis_client_is_missing() -> None:
    limiter = RateLimiter(max_requests=0, window_seconds=60, scope="test")
    req = _request(None)
    await limiter(req)  # type: ignore[arg-type]
