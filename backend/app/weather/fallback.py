"""FallbackWeatherProvider — automatic redundancy between two sources.

Wraps a primary and a secondary ``WeatherProvider``: each interface method
is tried on the primary first; if it raises ``WeatherProviderUnavailableError``
or ``httpx.HTTPError``, the same call is retried on the secondary. If both
fail, the secondary's error propagates (already caught by the same except
clauses callers use today — see ``app.weather.provider
.WeatherProviderUnavailableError``).

Built for INMET (primary, proven unstable in production) + CPTEC (secondary)
— see ADR-0011 — but is generic: it works for any two ``WeatherProvider``
implementations. Per-method fallback (not a whole-provider swap) matters
here because CPTEC has no radar/current-conditions data at all — falling
back to it for ``get_radar_frames``/``get_current_data`` is a no-op that
still raises, exactly as if there were no fallback, while for
``get_forecast`` it provides genuine redundancy.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.core.enums import WeatherSourceKind
from app.core.metrics import external_api_latency, weather_source_used
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
    WeatherProviderUnavailableError,
)

logger = logging.getLogger(__name__)

_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)

_T = TypeVar("_T")


class FallbackWeatherProvider(WeatherProvider):
    """Tries ``primary`` first, falls back to ``secondary`` on failure."""

    def __init__(self, primary: WeatherProvider, secondary: WeatherProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def name(self) -> str:
        return f"{self._primary.name}+{self._secondary.name}"

    @property
    def kind(self) -> WeatherSourceKind:
        return self._primary.kind

    async def _call(
        self,
        method: str,
        primary_call: Callable[[], Awaitable[_T]],
        secondary_call: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Shared try-primary-then-secondary body (hardening ADR-0035): the
        five public methods below only differ in *which* provider call they
        make, so the fallback/metrics/logging logic lives here once instead
        of five times.
        """
        start = time.monotonic()
        try:
            result = await primary_call()
        except _RECOVERABLE as exc:
            external_api_latency.record(
                time.monotonic() - start, {"provider": self._primary.name, "method": method}
            )
            logger.warning(
                "%s %s unavailable (%s); falling back to %s",
                self._primary.name,
                method,
                exc,
                self._secondary.name,
            )
            start = time.monotonic()
            result = await secondary_call()
            external_api_latency.record(
                time.monotonic() - start, {"provider": self._secondary.name, "method": method}
            )
            weather_source_used.add(
                1, {"provider": self._secondary.name, "fallback": True, "method": method}
            )
            return result
        external_api_latency.record(
            time.monotonic() - start, {"provider": self._primary.name, "method": method}
        )
        weather_source_used.add(
            1, {"provider": self._primary.name, "fallback": False, "method": method}
        )
        return result

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        return await self._call(
            "get_current_data",
            lambda: self._primary.get_current_data(latitude, longitude),
            lambda: self._secondary.get_current_data(latitude, longitude),
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        return await self._call(
            "get_radar_frames",
            lambda: self._primary.get_radar_frames(limit=limit),
            lambda: self._secondary.get_radar_frames(limit=limit),
        )

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        return await self._call(
            "get_warnings",
            lambda: self._primary.get_warnings(latitude, longitude),
            lambda: self._secondary.get_warnings(latitude, longitude),
        )

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        return await self._call(
            "get_forecast",
            lambda: self._primary.get_forecast(latitude, longitude),
            lambda: self._secondary.get_forecast(latitude, longitude),
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        return await self._call(
            "get_recent_rainfall",
            lambda: self._primary.get_recent_rainfall(latitude, longitude, days=days),
            lambda: self._secondary.get_recent_rainfall(latitude, longitude, days=days),
        )

    async def aclose(self) -> None:
        for provider in (self._primary, self._secondary):
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()
