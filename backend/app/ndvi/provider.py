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

from pydantic import BaseModel

from app.weather.provider import Provenance


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
