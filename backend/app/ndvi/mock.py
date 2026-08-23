"""MockNdviProvider — deterministic, clearly-labelled simulated data.

⚠️ Every value produced here is SIMULATED (``is_mock=True``). It exists to
develop and test the NDVI pipeline end-to-end without real Copernicus
credentials (FASE 29). It must never be presented to a user as a real
observation.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from app.core.enums import WeatherSourceKind
from app.ndvi.provider import NdviObservation, NdviProvider
from app.weather.provider import Provenance

_MOCK_NAME = "MOCK"


class MockNdviProvider(NdviProvider):
    """A reproducible fake source. Deterministic given the polygon itself —
    the same talhão always gets the same value in a given run, no
    randomness, so tests and manual QA aren't flaky."""

    def __init__(self, *, seed: float = 1.0) -> None:
        self._seed = seed

    @property
    def name(self) -> str:
        return _MOCK_NAME

    def _centroid(self, boundary_geojson: str) -> tuple[float, float]:
        ring = json.loads(boundary_geojson)["coordinates"][0]
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return sum(lons) / len(lons), sum(lats) / len(lats)

    async def get_ndvi(self, boundary_geojson: str, *, lookback_days: float) -> NdviObservation:
        lon, lat = self._centroid(boundary_geojson)
        # Bounded to a plausible vegetated-cropland range [0.15, 0.85] —
        # never the full theoretical [-1, 1] NDVI range, since bare
        # soil/water aren't what this feature is meant to be tested against.
        wave = (math.sin((lat + lon) * self._seed) + 1.0) / 2.0
        ndvi_mean = 0.15 + wave * 0.70
        return NdviObservation(
            provenance=Provenance(
                source_name=_MOCK_NAME, source_kind=WeatherSourceKind.MOCK, is_mock=True
            ),
            observed_at=datetime.now(UTC),
            ndvi_mean=round(ndvi_mean, 3),
            valid_pixel_percent=95.0,
        )
