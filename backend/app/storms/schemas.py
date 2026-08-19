"""Read schemas for storm cells and risk."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import RiskLevel, StormSeverity


class StormCellOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    detected_at: datetime
    latitude: float
    longitude: float
    severity: StormSeverity
    max_reflectivity: float | None
    average_reflectivity: float | None
    area_km2: float | None
    is_mock: bool


class NearbyStormCellOut(StormCellOut):
    """A storm cell plus its distance to the query point."""

    distance_km: float


class StormRiskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    storm_cell_id: uuid.UUID | None
    severity: RiskLevel
    rain_risk: float
    wind_risk: float
    hail_risk: float
    lightning_risk: float
    storm_distance_km: float | None
    storm_speed_kmh: float | None
    eta_minutes: int | None
    computed_at: datetime
    is_mock: bool
    experimental: bool
