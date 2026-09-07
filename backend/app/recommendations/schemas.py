"""Recommended-action API schemas (Fase 5, ADR-0089)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import RiskLevel


class RecommendedActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    rule_key: str
    title: str
    message: str
    level: RiskLevel
    alert_id: uuid.UUID | None
    created_at: datetime
