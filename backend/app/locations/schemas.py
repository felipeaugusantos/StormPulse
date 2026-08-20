"""Location and alert-preference schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AlertType


class AlertPreferenceIn(BaseModel):
    alert_type: AlertType
    enabled: bool = True


class AlertPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_type: AlertType
    enabled: bool


class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="other", max_length=40)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=50.0, gt=0, le=500)


class LocationCreate(LocationBase):
    # Optional initial set of enabled alert types.
    alert_preferences: list[AlertPreferenceIn] = Field(default_factory=list)


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: str | None = Field(default=None, max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=500)
    is_active: bool | None = None
    alert_preferences: list[AlertPreferenceIn] | None = None


class LocationOut(LocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    is_active: bool
    created_at: datetime
    alert_preferences: list[AlertPreferenceOut] = Field(default_factory=list)


class SprayWindowOut(BaseModel):
    """Live spray-safety check (FASE 19, rain-aware since FASE 20, humidity/
    inversion-aware since FASE 22).

    Originally wind-only — INMET/CPTEC never gave numeric precipitation
    forecast (ADR-0014). Open-Meteo does (ADR-0015), so rain is now weighed
    in *when available*; wind alone still decides ``safe`` when it isn't
    (e.g. the active provider is still just INMET/CPTEC). Thermal-inversion
    risk (calm wind + high humidity, ADR-0018) is weighed in whenever the
    active source reports humidity.
    """

    wind_kmh: float | None
    wind_gusts_kmh: float | None
    max_wind_kmh: float
    rain_probability_percent: int | None
    rain_expected_mm: float | None
    max_rain_probability_percent: int
    humidity_percent: float | None
    inversion_risk: bool
    # None when wind wasn't reported at all — never guessed.
    safe: bool | None
