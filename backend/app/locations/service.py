"""Location CRUD, scoped to the authenticated user's tenant.

Geography is populated from lat/lon as a WGS84 point so PostGIS proximity
queries (``ST_DWithin``) work against it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.alerts.models import Alert
from app.alerts.schemas import AlertOut
from app.core.config import Settings
from app.core.enums import AlertEventType, VegetationIndex
from app.core.rls import set_tenant_context
from app.deforestation.models import DeforestationCheck
from app.deforestation.provider import DeforestationAlert
from app.locations.ai_summary import generate_report_summary
from app.locations.models import AlertPreference, Location
from app.locations.schemas import (
    AlertPreferenceIn,
    DeforestationCheckOut,
    LastAlertOut,
    LocationCreate,
    LocationUpdate,
    RiskDigestOut,
    SoilMoistureOut,
    WeeklyReportOut,
)
from app.ndvi.models import NdviReading
from app.ndvi.schemas import NdviOut
from app.organizations.permissions import can_access_location
from app.soilmoisture.factory import get_soil_moisture_provider
from app.soilmoisture.provider import SoilMoistureProviderUnavailableError
from app.storms import service as storm_service
from app.storms.schemas import StormRiskOut
from app.users.models import User
from app.weather.factory import get_weather_provider
from app.weather.provider import WeatherProviderUnavailableError

_WEEKLY_REPORT_DAYS = 7
_AGRO_ALERT_EVENTS = (AlertEventType.FROST_WARNING, AlertEventType.DRY_SPELL_WARNING)


def point_wkt(latitude: float, longitude: float) -> WKTElement:
    """A WGS84 (SRID 4326) point. Note PostGIS order is (lon, lat)."""
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def _apply_preferences(location: Location, prefs: list[AlertPreferenceIn]) -> None:
    location.alert_preferences = [
        AlertPreference(alert_type=p.alert_type, enabled=p.enabled) for p in prefs
    ]


async def create_location(session: AsyncSession, user: User, data: LocationCreate) -> Location:
    location = Location(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=data.name,
        kind=data.kind,
        latitude=data.latitude,
        longitude=data.longitude,
        radius_km=data.radius_km,
        geom=point_wkt(data.latitude, data.longitude),
        parent_location_id=data.parent_location_id,
        crop=data.crop,
        soil_type=data.soil_type,
        boundary_geojson=data.boundary_geojson,
        color=data.color,
    )
    _apply_preferences(location, data.alert_preferences)
    session.add(location)
    await session.commit()
    # commit() ends the transaction get_current_user's app.tenant_id was
    # scoped to (RLS, migration 0b7b9a5dbd11) — re-apply before the
    # post-commit re-fetch below, or it silently returns zero rows.
    await set_tenant_context(session, user.tenant_id)
    return await get_location(session, user, location.id)  # type: ignore[return-value]


async def list_locations(session: AsyncSession, user: User) -> list[Location]:
    result = await session.execute(
        select(Location)
        .where(Location.tenant_id == user.tenant_id)
        .options(selectinload(Location.alert_preferences))
        .order_by(Location.created_at.desc())
    )
    locations = list(result.scalars().all())
    return [
        location for location in locations if await can_access_location(session, user, location)
    ]


async def get_location(
    session: AsyncSession, user: User, location_id: uuid.UUID
) -> Location | None:
    result = await session.execute(
        select(Location)
        .where(
            Location.id == location_id,
            Location.tenant_id == user.tenant_id,
        )
        .options(selectinload(Location.alert_preferences))
    )
    location = result.scalar_one_or_none()
    if location is None or not await can_access_location(session, user, location):
        return None
    return location


async def update_location(
    session: AsyncSession, location: Location, data: LocationUpdate
) -> Location:
    fields = data.model_dump(exclude_unset=True, exclude={"alert_preferences"})
    for key, value in fields.items():
        setattr(location, key, value)

    if "latitude" in fields or "longitude" in fields:
        location.geom = point_wkt(location.latitude, location.longitude)

    if data.alert_preferences is not None:
        _apply_preferences(location, data.alert_preferences)

    await session.commit()
    # Same post-commit GUC loss as create_location above — the refresh
    # below re-queries locations to load the relationship's owning row.
    await set_tenant_context(session, location.tenant_id)
    await session.refresh(location, attribute_names=["alert_preferences"])
    return location


async def delete_location(session: AsyncSession, location: Location) -> None:
    await session.delete(location)
    await session.commit()


async def _gather_deforestation(
    session: AsyncSession, location_id: uuid.UUID
) -> DeforestationCheckOut | None:
    """Merges every source's last check (Amazônia DETER / Cerrado PRODES)
    into one summary — shared by the weekly report and the risk digest, so
    both show exactly the same reading."""
    deforestation_checks = list(
        (
            await session.execute(
                select(DeforestationCheck).where(DeforestationCheck.location_id == location_id)
            )
        )
        .scalars()
        .all()
    )
    if not deforestation_checks:
        return None
    deforestation_alerts: list[DeforestationAlert] = []
    for row in deforestation_checks:
        deforestation_alerts.extend(
            DeforestationAlert.model_validate(a) for a in json.loads(row.alerts_json)
        )
    return DeforestationCheckOut(
        checked_sources=[row.source for row in deforestation_checks],
        last_checked_at=max(row.checked_at for row in deforestation_checks),
        alerts=deforestation_alerts,
    )


async def _gather_soil_moisture(location: Location, settings: Settings) -> SoilMoistureOut | None:
    """The one live call in either the weekly report or the risk digest —
    NASA POWER (or its mock) has no per-location persistence, so there is
    no "already computed" reading to fall back to. A failure here never
    fails the caller; it just means this one signal is missing."""
    soil_moisture_provider = get_soil_moisture_provider(settings)
    try:
        observation = await soil_moisture_provider.get_soil_moisture(
            location.latitude, location.longitude
        )
        return SoilMoistureOut(
            observed_at=observation.observed_at,
            surface_wetness_percent=observation.surface_wetness_percent,
            root_zone_wetness_percent=observation.root_zone_wetness_percent,
            profile_wetness_percent=observation.profile_wetness_percent,
            is_mock=observation.provenance.is_mock,
        )
    except (SoilMoistureProviderUnavailableError, httpx.HTTPError):
        return None
    finally:
        await soil_moisture_provider.aclose()


async def _latest_alert_of_type(
    session: AsyncSession, location_id: uuid.UUID, event_type: AlertEventType
) -> Alert | None:
    stmt = (
        select(Alert)
        .where(Alert.location_id == location_id, Alert.event_type == event_type)
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _to_last_alert(alert: Alert | None) -> LastAlertOut | None:
    if alert is None:
        return None
    return LastAlertOut(
        occurred_at=alert.created_at, level=alert.level, title=alert.title, message=alert.message
    )


async def build_risk_digest(
    session: AsyncSession, location: Location, settings: Settings
) -> RiskDigestOut:
    """Reads every risk signal already computed/persisted for this
    location into one payload (Fase 3-A, ADR-0087) — never recalculates
    anything itself. Storm/NDVI/deforestation are exact reads of the
    latest already-materialized row; frost/dry-spell surface only the
    last `Alert` ever fired (see `LastAlertOut`); soil moisture is the one
    live call, same degrade-gracefully behavior as `build_weekly_report`.
    ZARC is deliberately excluded (live geocoding lookup, not a persisted
    per-location signal)."""
    storm_row = await storm_service.latest_risk_for_location(session, location.id)
    storm = StormRiskOut.model_validate(storm_row) if storm_row is not None else None

    ndvi_stmt = (
        select(NdviReading)
        .where(
            NdviReading.location_id == location.id,
            NdviReading.index_name == VegetationIndex.NDVI.value,
        )
        .order_by(NdviReading.observed_at.desc())
        .limit(1)
    )
    ndvi_row = (await session.execute(ndvi_stmt)).scalar_one_or_none()
    ndvi = NdviOut.model_validate(ndvi_row) if ndvi_row is not None else None

    deforestation = await _gather_deforestation(session, location.id)

    frost_alert = await _latest_alert_of_type(session, location.id, AlertEventType.FROST_WARNING)
    dry_spell_alert = await _latest_alert_of_type(
        session, location.id, AlertEventType.DRY_SPELL_WARNING
    )

    soil_moisture = (
        await _gather_soil_moisture(location, settings) if settings.soil_moisture_enabled else None
    )

    return RiskDigestOut(
        location_id=location.id,
        generated_at=datetime.now(UTC),
        storm=storm,
        ndvi=ndvi,
        deforestation=deforestation,
        frost_last_alert=_to_last_alert(frost_alert),
        dry_spell_last_alert=_to_last_alert(dry_spell_alert),
        soil_moisture=soil_moisture,
    )


async def build_weekly_report(
    session: AsyncSession, location: Location, settings: Settings
) -> WeeklyReportOut:
    """Shared by the JSON and PDF weekly-report endpoints — both must show
    exactly the same numbers, so there's only one place that computes
    them."""
    now = datetime.now(UTC)
    # Excludes today (partial day) — same convention as the dry-spell check
    # in workers/agro_pipeline.py: a still-in-progress day would understate
    # today's rainfall and skew the total.
    period_end = now.date() - timedelta(days=1)
    period_start = period_end - timedelta(days=_WEEKLY_REPORT_DAYS - 1)

    provider = get_weather_provider(settings)
    rainfall_total_mm = 0.0
    dry_days_count = 0
    try:
        rainfall = await provider.get_recent_rainfall(
            location.latitude, location.longitude, days=_WEEKLY_REPORT_DAYS + 1
        )
        week = [d for d in rainfall.daily if period_start <= d.date <= period_end]
        rainfall_total_mm = round(sum(d.total_mm for d in week), 1)
        dry_days_count = sum(
            1 for d in week if d.total_mm < settings.agro_dry_spell_rain_threshold_mm
        )
    except (WeatherProviderUnavailableError, httpx.HTTPError):
        # Degrades gracefully — alerts/NDVI below are still useful even
        # when the weather source is briefly unavailable.
        pass

    period_start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    alerts_stmt = (
        select(Alert)
        .where(
            Alert.location_id == location.id,
            Alert.event_type.in_(_AGRO_ALERT_EVENTS),
            Alert.created_at >= period_start_dt,
        )
        .order_by(Alert.created_at.desc())
    )
    alerts = list((await session.execute(alerts_stmt)).scalars().all())

    ndvi_stmt = (
        select(NdviReading)
        .where(
            NdviReading.location_id == location.id,
            NdviReading.index_name == VegetationIndex.NDVI.value,
            NdviReading.observed_at >= period_start_dt,
        )
        .order_by(NdviReading.observed_at.asc())
    )
    ndvi_readings = list((await session.execute(ndvi_stmt)).scalars().all())

    deforestation = await _gather_deforestation(session, location.id)
    soil_moisture = (
        await _gather_soil_moisture(location, settings) if settings.soil_moisture_enabled else None
    )

    report = WeeklyReportOut(
        location_id=location.id,
        location_name=location.name,
        crop=location.crop,
        area_ha=location.area_ha,
        period_start=period_start,
        period_end=period_end,
        rainfall_total_mm=rainfall_total_mm,
        dry_days_count=dry_days_count,
        alerts=[AlertOut.model_validate(a) for a in alerts],
        ndvi_readings=[NdviOut.model_validate(n) for n in ndvi_readings],
        deforestation=deforestation,
        soil_moisture=soil_moisture,
        generated_at=now,
    )
    report.ai_summary = await generate_report_summary(report, settings)
    return report
