"""Alert read schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import AlertEventType, RiskLevel


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    storm_cell_id: uuid.UUID | None
    event_type: AlertEventType
    level: RiskLevel
    title: str
    message: str
    created_at: datetime
