"""Tests for FallbackWeatherProvider — automatic primary/secondary redundancy.

Uses small fake ``WeatherProvider`` implementations (not real INMET/CPTEC)
so the fallback logic itself is verified in isolation, independent of any
live network shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.enums import WeatherSourceKind
from app.weather.fallback import FallbackWeatherProvider
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    Provenance,
    RadarFrameData,
    Warning,
    WeatherProvider,
    WeatherProviderUnavailableError,
)


class _FakeProvider(WeatherProvider):
    def __init__(self, name: str, *, fails: bool = False, via_http_error: bool = False) -> None:
        self._name = name
        self._fails = fails
        self._via_http_error = via_http_error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.STATION

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self._fails:
            if self._via_http_error:
                raise httpx.ConnectError("boom", request=httpx.Request("GET", "http://x"))
            raise WeatherProviderUnavailableError(f"{self._name} unavailable")

    def _provenance(self) -> Provenance:
        return Provenance(source_name=self._name, source_kind=self.kind, is_mock=False)

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        self._maybe_fail()
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=datetime.now(UTC),
            latitude=latitude,
            longitude=longitude,
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        self._maybe_fail()
        return [RadarFrameData(provenance=self._provenance(), captured_at=datetime.now(UTC))]

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        self._maybe_fail()
        return []

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        self._maybe_fail()
        return Forecast(provenance=self._provenance(), latitude=latitude, longitude=longitude)


async def test_uses_primary_when_it_succeeds() -> None:
    primary = _FakeProvider("primary")
    secondary = _FakeProvider("secondary")
    provider = FallbackWeatherProvider(primary, secondary)

    forecast = await provider.get_forecast(-21.0, -47.0)

    assert forecast.provenance.source_name == "primary"
    assert primary.calls == 1
    assert secondary.calls == 0


async def test_falls_back_when_primary_raises_unavailable() -> None:
    primary = _FakeProvider("primary", fails=True)
    secondary = _FakeProvider("secondary")
    provider = FallbackWeatherProvider(primary, secondary)

    forecast = await provider.get_forecast(-21.0, -47.0)

    assert forecast.provenance.source_name == "secondary"
    assert primary.calls == 1
    assert secondary.calls == 1


async def test_falls_back_when_primary_raises_http_error() -> None:
    primary = _FakeProvider("primary", fails=True, via_http_error=True)
    secondary = _FakeProvider("secondary")
    provider = FallbackWeatherProvider(primary, secondary)

    conditions = await provider.get_current_data(-21.0, -47.0)

    assert conditions.provenance.source_name == "secondary"


async def test_propagates_when_both_fail() -> None:
    primary = _FakeProvider("primary", fails=True)
    secondary = _FakeProvider("secondary", fails=True)
    provider = FallbackWeatherProvider(primary, secondary)

    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_forecast(-21.0, -47.0)


async def test_applies_per_method_independently() -> None:
    # Radar frames fail on both (CPTEC never has radar data) while forecast
    # succeeds via fallback — matches the real INMET+CPTEC composition.
    primary = _FakeProvider("primary", fails=True)
    secondary = _FakeProvider("secondary")
    provider = FallbackWeatherProvider(primary, secondary)

    forecast = await provider.get_forecast(-21.0, -47.0)
    assert forecast.provenance.source_name == "secondary"

    warnings = await provider.get_warnings(-21.0, -47.0)
    assert warnings == []
