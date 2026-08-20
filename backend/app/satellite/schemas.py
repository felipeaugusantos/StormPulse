"""Read schemas for satellite-derived convective watches (FASE 16)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConvectiveWatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_detected_at: datetime
    detected_at: datetime
    latitude: float
    longitude: float
    min_brightness_temp_k: float
    area_km2: float | None
    speed_kmh: float | None
    direction_deg: float | None
    is_active: bool
    is_mock: bool
    experimental: bool


class NearbyConvectiveWatchOut(ConvectiveWatchOut):
    """A convective watch plus its distance to the query point."""

    distance_km: float
