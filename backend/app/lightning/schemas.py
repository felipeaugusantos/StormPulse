"""Read schemas for lightning strikes (FASE 23)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LightningStrikeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    detected_at: datetime
    latitude: float
    longitude: float
    is_mock: bool


class NearbyLightningStrikeOut(LightningStrikeOut):
    """A lightning strike plus its distance to the query point."""

    distance_km: float
