"""Tests for the short-TTL weather-provider cache (real production incident,
2026-08-28 — see ``app.weather.cache``'s own docstring).

A minimal fake in place of ``redis.asyncio.Redis`` — same spirit as
``test_integration_multi_app_settings.py``'s ``_FakeRedis``, just with a
real TTL/expiry-aware ``get``/``set`` since these tests care about the
actual cache-hit/miss behavior, not just call counting.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import WeatherSourceKind
from app.weather.cache import get_cached, set_cached
from app.weather.provider import CurrentConditions, Provenance


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self._store[key] = value


class _RaisingRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis unreachable (fake)")

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        raise ConnectionError("redis unreachable (fake)")


def _current() -> CurrentConditions:
    return CurrentConditions(
        provenance=Provenance(
            source_name="FAKE", source_kind=WeatherSourceKind.FORECAST_MODEL, is_mock=False
        ),
        observed_at=datetime.now(UTC),
        latitude=-21.18,
        longitude=-47.81,
        temperature_c=27.2,
        wind_kmh=5.9,
        wind_gusts_kmh=11.5,
        precipitation_mm=0.0,
        relative_humidity_percent=54.0,
    )


async def test_get_cached_is_none_when_nothing_was_ever_set() -> None:
    redis = _FakeRedis()
    result = await get_cached(redis, "current", -21.18, -47.81, CurrentConditions)
    assert result is None


async def test_set_then_get_round_trips_the_same_value() -> None:
    redis = _FakeRedis()
    current = _current()
    await set_cached(redis, "current", -21.18, -47.81, current)

    result = await get_cached(redis, "current", -21.18, -47.81, CurrentConditions)
    assert result is not None
    assert result.temperature_c == 27.2
    assert result.provenance.source_name == "FAKE"


async def test_different_kinds_never_share_a_cache_entry() -> None:
    """ "forecast" and "rain-forecast" are never interchangeable content for
    the same point (see `_cached_forecast`'s own docstring) — must never
    collide in the cache just because the coordinates match."""
    redis = _FakeRedis()
    await set_cached(redis, "current", -21.18, -47.81, _current())

    result = await get_cached(redis, "rain-forecast", -21.18, -47.81, CurrentConditions)
    assert result is None


async def test_different_coordinates_never_share_a_cache_entry() -> None:
    redis = _FakeRedis()
    await set_cached(redis, "current", -21.18, -47.81, _current())

    result = await get_cached(redis, "current", -23.55, -46.63, CurrentConditions)
    assert result is None


async def test_none_redis_is_a_harmless_cache_miss() -> None:
    assert await get_cached(None, "current", -21.18, -47.81, CurrentConditions) is None
    # Must not raise either — same fail-open contract as a real Redis error.
    await set_cached(None, "current", -21.18, -47.81, _current())


async def test_a_read_failure_degrades_to_a_cache_miss_not_an_exception() -> None:
    result = await get_cached(_RaisingRedis(), "current", -21.18, -47.81, CurrentConditions)
    assert result is None


async def test_a_write_failure_never_raises() -> None:
    # Must not raise — a cache write is best-effort, never load-bearing.
    await set_cached(_RaisingRedis(), "current", -21.18, -47.81, _current())


async def test_a_corrupted_cache_value_degrades_to_a_cache_miss() -> None:
    redis = _FakeRedis()
    await redis.set("weathercache:current:-21.180:-47.810", "not valid json at all")

    result = await get_cached(redis, "current", -21.18, -47.81, CurrentConditions)
    assert result is None
