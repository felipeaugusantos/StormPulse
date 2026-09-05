"""MockNdviProvider — deterministic, clearly-labelled simulated data.

⚠️ Every value produced here is SIMULATED (``is_mock=True``). It exists to
develop and test the NDVI pipeline end-to-end without real Copernicus
credentials (FASE 29). It must never be presented to a user as a real
observation.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from datetime import UTC, datetime

from app.core.enums import ImageQuality, VegetationIndex, WeatherSourceKind
from app.ndvi.provider import NdviObservation, NdviProvider
from app.weather.provider import Provenance

_MOCK_NAME = "MOCK"
_PLACEHOLDER_SIZE_PX = 8
# A flat muted green — nowhere near the real evalscript's colour ramp,
# deliberately: this must never be mistaken for a real vegetation reading.
_PLACEHOLDER_RGB = (90, 140, 90)


def _placeholder_png() -> bytes:
    """A tiny solid-color PNG built from stdlib alone (`zlib`/`struct`) —
    PIL/numpy only ship in the `-satellite` image variant (see
    `workers/satellite_pipeline.py`'s own note on this), and the `api`
    container serving `get_ndvi_image` doesn't have them. Real providers
    render their image server-side and hand back finished bytes, so this
    is the only path that would otherwise need a local image library."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    size = _PLACEHOLDER_SIZE_PX
    row = bytes([0]) + bytes(_PLACEHOLDER_RGB) * size  # filter byte + RGB pixels
    raw = row * size
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


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

    async def get_ndvi_image(self, boundary_geojson: str, *, lookback_days: float) -> bytes:
        return _placeholder_png()

    async def get_index_history(
        self,
        boundary_geojson: str,
        *,
        indices: tuple[VegetationIndex, ...],
        lookback_days: float,
    ) -> list[NdviObservation]:
        base = await self.get_ndvi(boundary_geojson, lookback_days=lookback_days)
        offsets = {
            VegetationIndex.NDVI: 0.0,
            VegetationIndex.NDRE: -0.08,
            VegetationIndex.EVI: -0.04,
            VegetationIndex.NDMI: -0.18,
            VegetationIndex.NDWI: -0.28,
        }
        return [
            base.model_copy(
                update={
                    "index_name": index_name,
                    "ndvi_mean": round(base.ndvi_mean + offsets[index_name], 3),
                    "cloud_cover_percent": 5.0,
                    "quality": ImageQuality.HIGH,
                    "reliable": True,
                }
            )
            for index_name in indices
        ]

    async def get_index_image(
        self,
        boundary_geojson: str,
        *,
        index_name: VegetationIndex,
        observed_at: datetime,
    ) -> bytes:
        return _placeholder_png()
