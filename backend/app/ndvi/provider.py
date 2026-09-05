"""NdviProvider abstraction and its data-transfer object (FASE 29, ADR-0053).

Mirrors `app.weather.provider`'s shape (an ABC + a DTO carrying explicit
provenance) but scoped to exactly one operation — NDVI only ever applies to
a talhão's drawn polygon (`Location.boundary_geojson`), never to a plain
lat/lon point, so there's no `get_current_data`/`get_forecast`-style surface
to define here.
"""

from __future__ import annotations

import abc
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import ImageQuality, VegetationIndex
from app.weather.provider import Provenance


class VigorZone(BaseModel):
    label: str
    min_value: float
    max_value: float
    pixel_percent: float


class NdviObservation(BaseModel):
    provenance: Provenance
    # The satellite acquisition date the statistics came from — not "now".
    observed_at: datetime
    ndvi_mean: float
    # 0-100 — share of the polygon's pixels that had usable (non-cloud,
    # non-nodata) data in that acquisition. Low values mean `ndvi_mean` is
    # only representative of a small sliver of the talhão; the frontend
    # decides whether that's still worth showing.
    valid_pixel_percent: float
    index_name: VegetationIndex = VegetationIndex.NDVI
    cloud_cover_percent: float = 0.0
    quality: ImageQuality = ImageQuality.HIGH
    reliable: bool = True
    vigor_zones: list[VigorZone] = Field(default_factory=list)


class NdviProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot honestly produce an NDVI reading —
    auth failure, network error, or no valid (non-cloud) pixels anywhere in
    the lookback window. Callers must never substitute a stale or synthetic
    value silently when this is raised (same rule as
    `WeatherProviderUnavailableError`)."""


class NdviProvider(abc.ABC):
    """Interface every NDVI source must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def get_ndvi(self, boundary_geojson: str, *, lookback_days: float) -> NdviObservation:
        """`boundary_geojson` is a GeoJSON Polygon serialized as a JSON
        string — the exact same format `Location.boundary_geojson` is
        stored/validated in (see `app.locations.schemas`)."""
        ...

    @abc.abstractmethod
    async def get_ndvi_image(self, boundary_geojson: str, *, lookback_days: float) -> bytes:
        """A colored NDVI visualization (PNG bytes) over the same polygon
        and lookback window as `get_ndvi` — item "imagem do talhão" in the
        weekly report. A separate call from `get_ndvi`: real providers
        typically render this via a different API (an image-rendering
        endpoint, not the numeric-statistics one), so the two aren't
        assumed to share a request under the hood."""
        ...

    async def get_index_history(
        self,
        boundary_geojson: str,
        *,
        indices: tuple[VegetationIndex, ...],
        lookback_days: float,
    ) -> list[NdviObservation]:
        """Return every valid acquisition available in the lookback.

        The compatibility fallback lets older/custom providers continue to
        supply NDVI while new providers can fetch all indices in one call.
        """
        if VegetationIndex.NDVI not in indices:
            return []
        return [await self.get_ndvi(boundary_geojson, lookback_days=lookback_days)]

    async def get_index_image(
        self,
        boundary_geojson: str,
        *,
        index_name: VegetationIndex,
        observed_at: datetime,
    ) -> bytes:
        if index_name != VegetationIndex.NDVI:
            raise NdviProviderUnavailableError(f"Imagem {index_name.value.upper()} indisponível")
        return await self.get_ndvi_image(boundary_geojson, lookback_days=1.0)
