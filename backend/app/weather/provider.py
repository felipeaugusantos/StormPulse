"""WeatherProvider abstraction and its data-transfer objects.

No concrete source (INMET, INPE/CPTEC, CEMADEN, radars, commercial APIs) is
ever coupled to the storm engine — everything flows through this interface.
Every DTO carries provenance so simulated data can never masquerade as real.
"""

from __future__ import annotations

import abc
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import WeatherSourceKind


class Provenance(BaseModel):
    """Where a piece of data came from — always explicit."""

    source_name: str
    source_kind: WeatherSourceKind
    is_mock: bool


class CurrentConditions(BaseModel):
    provenance: Provenance
    observed_at: datetime
    latitude: float
    longitude: float
    temperature_c: float | None = None
    wind_kmh: float | None = None
    wind_gusts_kmh: float | None = None
    precipitation_mm: float | None = None
    relative_humidity_percent: float | None = None


class RawCell(BaseModel):
    """A raw cell candidate as reported by a source (pre-detection)."""

    latitude: float
    longitude: float
    max_reflectivity: float | None = None
    average_reflectivity: float | None = None
    area_km2: float | None = None


class RadarFrameData(BaseModel):
    provenance: Provenance
    captured_at: datetime
    cells: list[RawCell] = Field(default_factory=list)


class Warning(BaseModel):
    provenance: Provenance
    issued_at: datetime
    kind: str
    severity: str
    description: str


class ForecastPoint(BaseModel):
    time: datetime
    temperature_c: float | None = None
    # The day's low — distinct from `temperature_c` (which represents the
    # day's high, an INMET-inherited convention). Needed for frost risk;
    # not every source can populate it (see each provider's docstring).
    temperature_min_c: float | None = None
    precipitation_probability: int | None = None
    precipitation_mm: float | None = None


class Forecast(BaseModel):
    provenance: Provenance
    latitude: float
    longitude: float
    points: list[ForecastPoint] = Field(default_factory=list)


class DailyRainfall(BaseModel):
    date: date
    total_mm: float


class RainfallHistory(BaseModel):
    provenance: Provenance
    latitude: float
    longitude: float
    daily: list[DailyRainfall] = Field(default_factory=list)


class WeatherProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot honestly produce the requested data.

    Shared base for every concrete provider's own exception (e.g.
    ``InmetWeatherProvider``'s and ``CptecWeatherProvider``'s) so callers —
    including ``FallbackWeatherProvider`` and API routers — can catch one
    type regardless of which source is active. Callers must never
    substitute mock data silently under a "real" provenance when this is
    raised.
    """


class WeatherProvider(abc.ABC):
    """Interface every weather source must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def kind(self) -> WeatherSourceKind: ...

    @abc.abstractmethod
    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions: ...

    @abc.abstractmethod
    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]: ...

    @abc.abstractmethod
    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]: ...

    @abc.abstractmethod
    async def get_forecast(self, latitude: float, longitude: float) -> Forecast: ...

    @abc.abstractmethod
    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory: ...
