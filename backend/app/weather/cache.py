"""Short-TTL Redis cache for the weather-provider read endpoints.

Real production incident (2026-08-28): the dashboard polls each open
location's current-conditions/forecast every ~30s (`Dashboard.tsx`'s
`REFRESH_MS`), and each poll re-fetches `selectedLocation` as a fresh
object, re-triggering `LocationWeatherCard`'s own fetch — every open tab
was making a genuinely new upstream call every 30s, all funneling through
the same shared Open-Meteo forecast endpoint (`api.open-meteo.com/v1/
forecast`, used by both `get_current_data` and `get_forecast`) once INMET/
CPTEC fall through. The archive endpoint (`get_recent_rainfall`, called
far less often) kept working fine while the forecast endpoint started
failing fast and consistently — the signature of a rate/quota limit, not a
generic outage. This cache cuts that call volume down without changing
what any endpoint returns when the cache is cold or Redis is unavailable.

Fails open like ``app.core.ratelimit`` — a Redis error here degrades to
"just call the provider", never to an error response.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

# Untyped on purpose, same as `app.core.ratelimit`'s own
# `getattr(request.app.state, "redis", None)` — `redis.asyncio.Redis`'s real
# method signatures don't structurally satisfy a hand-written Protocol
# cleanly under mypy, and every call here is already wrapped in a broad
# `except Exception` regardless (fail-open), so nothing is gained by
# fighting that for a couple of duck-typed calls.
_Redis = Any

# Weather doesn't change meaningfully minute to minute for this use case —
# 5 minutes trades a small amount of staleness for a large cut in upstream
# call volume (a dashboard tab left open all day would otherwise make ~120
# calls/hour per location instead of ~12).
DEFAULT_TTL_SECONDS = 300


def _cache_key(kind: str, latitude: float, longitude: float) -> str:
    # Rounded to ~100m — coalesces near-duplicate points (e.g. a farm and a
    # talhão a few meters apart) onto the same cache entry without losing
    # meaningful precision for weather data.
    return f"weathercache:{kind}:{latitude:.3f}:{longitude:.3f}"


async def get_cached(
    redis: _Redis | None, kind: str, latitude: float, longitude: float, model: type[_T]
) -> _T | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(_cache_key(kind, latitude, longitude))
    except Exception as exc:  # noqa: BLE001 - fail open on cache errors
        logger.warning("weather cache read failed, bypassing", extra={"error": str(exc)})
        return None
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValueError:
        return None


async def set_cached(
    redis: _Redis | None,
    kind: str,
    latitude: float,
    longitude: float,
    value: BaseModel,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    if redis is None:
        return
    try:
        await redis.set(
            _cache_key(kind, latitude, longitude), value.model_dump_json(), ex=ttl_seconds
        )
    except Exception as exc:  # noqa: BLE001 - fail open on cache errors
        logger.warning("weather cache write failed, ignoring", extra={"error": str(exc)})
