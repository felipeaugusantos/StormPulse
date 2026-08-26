"""Location CRUD, scoped to the authenticated user's tenant.

Geography is populated from lat/lon as a WGS84 point so PostGIS proximity
queries (``ST_DWithin``) work against it.
"""

from __future__ import annotations

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
from app.core.enums import AlertEventType
from app.core.rls import set_tenant_context
from app.locations.models import AlertPreference, Location
from app.locations.schemas import (
    AlertPreferenceIn,
    LocationCreate,
    LocationUpdate,
    WeeklyReportOut,
)
from app.ndvi.models import NdviReading
from app.ndvi.schemas import NdviOut
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
        .where(Location.tenant_id == user.tenant_id, Location.user_id == user.id)
        .options(selectinload(Location.alert_preferences))
        .order_by(Location.created_at.desc())
    )
    return list(result.scalars().all())


async def get_location(
    session: AsyncSession, user: User, location_id: uuid.UUID
) -> Location | None:
    result = await session.execute(
        select(Location)
        .where(
            Location.id == location_id,
            Location.tenant_id == user.tenant_id,
            Location.user_id == user.id,
        )
        .options(selectinload(Location.alert_preferences))
    )
    return result.scalar_one_or_none()


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
        .where(NdviReading.location_id == location.id, NdviReading.observed_at >= period_start_dt)
        .order_by(NdviReading.observed_at.asc())
    )
    ndvi_readings = list((await session.execute(ndvi_stmt)).scalars().all())

    return WeeklyReportOut(
        location_id=location.id,
        location_name=location.name,
        crop=location.crop,
        period_start=period_start,
        period_end=period_end,
        rainfall_total_mm=rainfall_total_mm,
        dry_days_count=dry_days_count,
        alerts=[AlertOut.model_validate(a) for a in alerts],
        ndvi_readings=[NdviOut.model_validate(n) for n in ndvi_readings],
        generated_at=now,
    )
