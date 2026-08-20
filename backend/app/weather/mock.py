"""MockWeatherProvider — deterministic, clearly-labelled simulated data.

⚠️ Every value produced here is SIMULATED (``is_mock=True``). It exists to
develop and test the pipeline end-to-end before real integrations (FASE 13).
It must never be presented to a user as a real observation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.core.enums import WeatherSourceKind
from app.weather.provider import (
    CurrentConditions,
    DailyRainfall,
    Forecast,
    ForecastPoint,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    RawCell,
    Warning,
    WeatherProvider,
)

_MOCK_NAME = "MOCK"


class MockWeatherProvider(WeatherProvider):
    """A reproducible fake source. Deterministic given (lat, lon, time)."""

    def __init__(self, *, seed: float = 1.0) -> None:
        self._seed = seed

    @property
    def name(self) -> str:
        return _MOCK_NAME

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.MOCK

    def _provenance(self) -> Provenance:
        return Provenance(source_name=_MOCK_NAME, source_kind=self.kind, is_mock=True)

    def _wave(self, latitude: float, longitude: float, phase: float) -> float:
        """A smooth, bounded pseudo-value in [0, 1] — no randomness, reproducible."""
        return (math.sin((latitude + longitude) * self._seed + phase) + 1.0) / 2.0

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        w = self._wave(latitude, longitude, 0.0)
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=datetime.now(UTC),
            latitude=latitude,
            longitude=longitude,
            temperature_c=round(15 + 15 * w, 1),
            wind_kmh=round(5 + 30 * w, 1),
            wind_gusts_kmh=round(10 + 60 * w, 1),
            precipitation_mm=round(20 * self._wave(latitude, longitude, 1.5), 1),
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        now = datetime.now(UTC)
        frames: list[RadarFrameData] = []
        for i in range(limit):
            captured_at = now - timedelta(minutes=5 * (limit - 1 - i))
            # A single drifting mock cell so tracking has something to follow.
            drift = 0.05 * i
            frames.append(
                RadarFrameData(
                    provenance=self._provenance(),
                    captured_at=captured_at,
                    cells=[
                        RawCell(
                            latitude=-23.5 + drift,
                            longitude=-46.6 + drift,
                            max_reflectivity=round(45 + 10 * self._wave(i, i, 0.3), 1),
                            average_reflectivity=round(30 + 8 * self._wave(i, i, 0.6), 1),
                            area_km2=round(40 + 20 * self._wave(i, i, 0.9), 1),
                        )
                    ],
                )
            )
        return frames

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        # Mock: emit a single advisory only when the mock field is "high".
        if self._wave(latitude, longitude, 2.0) < 0.75:
            return []
        return [
            Warning(
                provenance=self._provenance(),
                issued_at=datetime.now(UTC),
                kind="severe_storm",
                severity="orange",
                description="[MOCK] Aviso simulado de tempestade para desenvolvimento.",
            )
        ]

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        now = datetime.now(UTC)
        points = [
            ForecastPoint(
                time=now + timedelta(hours=h),
                temperature_c=round(15 + 15 * self._wave(latitude, longitude, h * 0.2), 1),
                temperature_min_c=round(7 + 15 * self._wave(latitude, longitude, h * 0.2), 1),
                precipitation_probability=int(100 * self._wave(latitude, longitude, h * 0.3)),
                precipitation_mm=round(10 * self._wave(latitude, longitude, h * 0.4), 1),
            )
            for h in range(12)
        ]
        return Forecast(
            provenance=self._provenance(),
            latitude=latitude,
            longitude=longitude,
            points=points,
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        today = datetime.now(UTC).date()
        daily = [
            DailyRainfall(
                date=today - timedelta(days=d),
                total_mm=round(15 * self._wave(latitude, longitude, d * 0.5), 1),
            )
            for d in range(days)
        ]
        return RainfallHistory(
            provenance=self._provenance(),
            latitude=latitude,
            longitude=longitude,
            daily=daily,
        )
