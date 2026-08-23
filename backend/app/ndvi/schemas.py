"""NDVI API schemas (FASE 29, ADR-0053)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NdviOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observed_at: datetime
    ndvi_mean: float
    valid_pixel_percent: float
    is_mock: bool
