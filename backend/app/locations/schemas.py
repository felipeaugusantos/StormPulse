"""Location and alert-preference schemas."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.alerts.schemas import AlertOut
from app.core.enums import AlertType
from app.ndvi.schemas import NdviOut

_MIN_POLYGON_RING_POINTS = 4
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# The three main ZARC soil-texture classes (Cod_Solo 1/2/3 in the MAPA
# dictionary) — the more specialized AD1-AD6 water-holding-capacity
# classes some crops also use aren't offered here, to keep the picker
# simple (item ZARC, ADR-0069).
_SOIL_TYPES = {"arenoso", "textura_media", "argiloso"}


def _validate_soil_type(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in _SOIL_TYPES:
        raise ValueError(f"soil_type precisa ser um de: {', '.join(sorted(_SOIL_TYPES))}")
    return value


def _validate_color(value: str | None) -> str | None:
    """Shared by ``LocationCreate``/``LocationUpdate`` — a manual override
    for the talhão's map color (FASE 27, ADR-0025), replacing the
    crop-name-derived default. `#RRGGBB` only — never used for anything but
    rendering."""
    if value is None:
        return None
    if not _HEX_COLOR_RE.match(value):
        raise ValueError("color precisa ser um hex #RRGGBB")
    return value


def _validate_boundary_geojson(value: str | None) -> str | None:
    """Shared by ``LocationCreate``/``LocationUpdate`` — only checked for
    being *parseable* GeoJSON, never used for weather/agro lookups (those
    keep using latitude/longitude)."""
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("boundary_geojson não é um JSON válido") from exc
    if not isinstance(parsed, dict) or parsed.get("type") != "Polygon":
        raise ValueError("boundary_geojson precisa ser um GeoJSON Polygon")
    coordinates = parsed.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) == 0
        or not isinstance(coordinates[0], list)
        or len(coordinates[0]) < _MIN_POLYGON_RING_POINTS
    ):
        raise ValueError(
            "boundary_geojson precisa de um anel com pelo menos "
            f"{_MIN_POLYGON_RING_POINTS} pontos (incluindo o de fechamento)"
        )
    return value


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
    # Talhão support (FASE 26): present → this location is a plot inside
    # the parent farm. Validated in the router (same tenant/user, parent
    # isn't itself a plot) since that needs a DB lookup.
    parent_location_id: uuid.UUID | None = None
    crop: str | None = Field(default=None, max_length=60)
    # Soil texture class (item ZARC, ADR-0069) — needed to match the
    # talhão's crop+município against the right ZARC planting window.
    soil_type: str | None = Field(default=None)
    # Visual-only polygon outline (FASE 27, ADR-0024) — a GeoJSON Polygon
    # serialized as a JSON string, e.g. {"type":"Polygon","coordinates":
    # [[[lng,lat],...]]}. Never used for weather/agro lookups — those keep
    # using latitude/longitude above — so it's stored and returned as an
    # opaque string, only checked here for being *parseable* GeoJSON.
    boundary_geojson: str | None = Field(default=None)
    # Manual color override (FASE 27, ADR-0025) — when unset, the frontend
    # derives a color from `crop` instead (see `web/src/cropColors.ts`).
    color: str | None = Field(default=None)

    _check_boundary_geojson = field_validator("boundary_geojson")(_validate_boundary_geojson)
    _check_color = field_validator("color")(_validate_color)
    _check_soil_type = field_validator("soil_type")(_validate_soil_type)


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
    crop: str | None = Field(default=None, max_length=60)
    soil_type: str | None = Field(default=None)
    boundary_geojson: str | None = Field(default=None)
    color: str | None = Field(default=None)

    _check_boundary_geojson = field_validator("boundary_geojson")(_validate_boundary_geojson)
    _check_color = field_validator("color")(_validate_color)
    _check_soil_type = field_validator("soil_type")(_validate_soil_type)


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


class WeeklyReportOut(BaseModel):
    """Weekly summary for a single talhão (FASE 32) — something concrete to
    show an agronomist or a bank, not just live numbers on a dashboard.
    Only ever built from data already real: rainfall history from the
    weather provider, alerts and NDVI readings already persisted. Never
    fabricates a week of history that wasn't actually observed."""

    location_id: uuid.UUID
    location_name: str
    crop: str | None
    period_start: date
    period_end: date
    rainfall_total_mm: float
    dry_days_count: int
    alerts: list[AlertOut]
    ndvi_readings: list[NdviOut]
    generated_at: datetime


class ZarcMatchOut(BaseModel):
    """One MAPA-published ZARC row matching the talhão's crop/solo/
    município — a talhão can match more than one (different cultivar
    cycle groups have different windows for the same crop), never merged
    into a single guessed number here."""

    cultura: str
    cod_ciclo: int
    ciclo_label: str
    safra_ini: int
    safra_fin: int
    portaria: str | None
    # 36 ten-day periods of the year, in order — 0 means "not a
    # recommended window", a non-zero value is the official risk
    # percentage tier (20/30/40 — lower is safer).
    decendios: list[int]


class ZarcWindowOut(BaseModel):
    """Planting-window info for a single talhão (item ZARC, ADR-0069) —
    purely informational, never generates an alert on its own (no
    planting-date field exists yet to compare against)."""

    location_id: uuid.UUID
    geocodigo: str
    municipio: str
    uf: str
    matches: list[ZarcMatchOut]
