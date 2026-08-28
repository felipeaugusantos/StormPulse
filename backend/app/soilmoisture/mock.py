"""MockSoilMoistureProvider — deterministic, no network.

Exists to exercise the report plumbing end-to-end without depending on
NASA POWER's public API — it must never be presented to a user as a real
observation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import WeatherSourceKind
from app.soilmoisture.provider import SoilMoistureObservation, SoilMoistureProvider
from app.weather.provider import Provenance

_MOCK_NAME = "MOCK"


class MockSoilMoistureProvider(SoilMoistureProvider):
    @property
    def name(self) -> str:
        return _MOCK_NAME

    async def get_soil_moisture(self, latitude: float, longitude: float) -> SoilMoistureObservation:
        return SoilMoistureObservation(
            provenance=Provenance(
                source_name=_MOCK_NAME, source_kind=WeatherSourceKind.MOCK, is_mock=True
            ),
            observed_at=datetime.now(UTC).date(),
            surface_wetness_percent=33.0,
            root_zone_wetness_percent=46.0,
            profile_wetness_percent=46.0,
        )
