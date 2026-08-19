"""Location CRUD, scoped to the authenticated user's tenant.

Geography is populated from lat/lon as a WGS84 point so PostGIS proximity
queries (``ST_DWithin``) work against it.
"""

from __future__ import annotations

import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.locations.models import AlertPreference, Location
from app.locations.schemas import AlertPreferenceIn, LocationCreate, LocationUpdate
from app.users.models import User


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
    )
    _apply_preferences(location, data.alert_preferences)
    session.add(location)
    await session.commit()
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
    await session.refresh(location, attribute_names=["alert_preferences"])
    return location


async def delete_location(session: AsyncSession, location: Location) -> None:
    await session.delete(location)
    await session.commit()
