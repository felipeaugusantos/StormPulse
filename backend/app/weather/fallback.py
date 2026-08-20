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

import httpx

from app.core.enums import WeatherSourceKind
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    RadarFrameData,
    Warning,
    WeatherProvider,
    WeatherProviderUnavailableError,
)

logger = logging.getLogger(__name__)

_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)


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

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        try:
            return await self._primary.get_current_data(latitude, longitude)
        except _RECOVERABLE as exc:
            logger.warning(
                "%s current-conditions unavailable (%s); falling back to %s",
                self._primary.name,
                exc,
                self._secondary.name,
            )
            return await self._secondary.get_current_data(latitude, longitude)

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        try:
            return await self._primary.get_radar_frames(limit=limit)
        except _RECOVERABLE as exc:
            logger.warning(
                "%s radar frames unavailable (%s); falling back to %s",
                self._primary.name,
                exc,
                self._secondary.name,
            )
            return await self._secondary.get_radar_frames(limit=limit)

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        try:
            return await self._primary.get_warnings(latitude, longitude)
        except _RECOVERABLE as exc:
            logger.warning(
                "%s warnings unavailable (%s); falling back to %s",
                self._primary.name,
                exc,
                self._secondary.name,
            )
            return await self._secondary.get_warnings(latitude, longitude)

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        try:
            return await self._primary.get_forecast(latitude, longitude)
        except _RECOVERABLE as exc:
            logger.warning(
                "%s forecast unavailable (%s); falling back to %s",
                self._primary.name,
                exc,
                self._secondary.name,
            )
            return await self._secondary.get_forecast(latitude, longitude)

    async def aclose(self) -> None:
        for provider in (self._primary, self._secondary):
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()
