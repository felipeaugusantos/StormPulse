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
    # Motion of the cell's active track, from its latest observation (see
    # engine/trajectory/estimator.py) — None when the cell has no active
    # track or fewer than 2 observations (never fabricated). The projected
    # position is a straight-line extrapolation at the current speed/
    # direction, not a real forecast — labeled as an estimate in the UI.
    speed_kmh: float | None = None
    direction_deg: float | None = None
    projected_latitude_1h: float | None = None
    projected_longitude_1h: float | None = None


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
    # FASE 9 (ADR-0060) — None when ANTHROPIC_API_KEY isn't configured,
    # generation is still pending, or severity was GREEN (not worth
    # explaining). Never a second source of risk, only a rephrasing of
    # this same object's other fields.
    ai_summary: str | None = None
