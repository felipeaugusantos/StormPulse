"""NDVI API schemas (FASE 29, ADR-0053)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import ImageQuality, VegetationIndex
from app.ndvi.provider import VigorZone


class NdviOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observed_at: datetime
    ndvi_mean: float
    valid_pixel_percent: float
    is_mock: bool


class VegetationReadingOut(BaseModel):
    id: str
    observed_at: datetime
    index_name: VegetationIndex
    value_mean: float
    source_name: str
    valid_pixel_percent: float
    cloud_cover_percent: float
    quality: ImageQuality
    reliable: bool
    vigor_zones: list[VigorZone]
    is_mock: bool


class VegetationAnomalyOut(BaseModel):
    status: str
    minimum_history: int
    baseline_count: int
    baseline_mean: float | None
    difference: float | None
    percent_difference: float | None
    z_score: float | None


class VegetationSeriesOut(BaseModel):
    location_id: str
    index_name: VegetationIndex
    current: VegetationReadingOut | None
    series: list[VegetationReadingOut]
    anomaly: VegetationAnomalyOut
    persistent_drop: bool


class VegetationComparisonOut(BaseModel):
    location_id: str
    index_name: VegetationIndex
    older: VegetationReadingOut
    newer: VegetationReadingOut
    absolute_change: float
    percent_change: float | None
