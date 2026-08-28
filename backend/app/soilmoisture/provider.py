"""SoilMoistureProvider abstraction — regional soil-wetness context for the
weekly report (item NASA).

Unlike NDVI (a per-talhão satellite reading over the drawn polygon), this is
a *regional* model-based estimate queried by lat/lon point — NASA POWER's
underlying GEOS reanalysis has a native resolution around 50km, coarser
even than SMAP's own ~9km satellite footprint. It's real NASA data and a
genuine complement to the rainfall numbers already in the report, but it is
never a per-talhão measurement — the report text says so explicitly, same
honesty rule as `DeforestationCheckOut`'s biome-coverage caveat.
"""

from __future__ import annotations

import abc
from datetime import date

from pydantic import BaseModel

from app.weather.provider import Provenance


class SoilMoistureObservation(BaseModel):
    provenance: Provenance
    # The date the underlying model estimate is for — not "now" (NASA
    # POWER's most recent 1-2 days are typically still processing and come
    # back as a fill value, see `nasa_power.py`).
    observed_at: date
    # 0-100 — fraction of saturation at each depth band, as a percentage.
    surface_wetness_percent: float
    root_zone_wetness_percent: float
    profile_wetness_percent: float


class SoilMoistureProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot honestly produce a soil-moisture
    reading — network error, or every requested day was a fill value."""


class SoilMoistureProvider(abc.ABC):
    """Interface every soil-moisture source must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def get_soil_moisture(
        self, latitude: float, longitude: float
    ) -> SoilMoistureObservation: ...

    async def aclose(self) -> None:  # pragma: no cover - overridden when needed
        return None
