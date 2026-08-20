"""Read queries for convective watches — same PostGIS pattern as storms/service.py."""

from __future__ import annotations

from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import ST_Distance, ST_DWithin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.satellite.models import ConvectiveWatch


def _point(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


async def list_active_watches(session: AsyncSession, *, limit: int = 100) -> list[ConvectiveWatch]:
    result = await session.execute(
        select(ConvectiveWatch)
        .where(ConvectiveWatch.is_active.is_(True))
        .order_by(ConvectiveWatch.detected_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def watches_within_radius(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    limit: int = 100,
) -> list[tuple[ConvectiveWatch, float]]:
    """Return (watch, distance_km) for active watches within radius."""
    point = _point(latitude, longitude)
    radius_m = radius_km * 1000.0
    distance_m = ST_Distance(ConvectiveWatch.centroid, point)

    result = await session.execute(
        select(ConvectiveWatch, distance_m.label("distance_m"))
        .where(
            ConvectiveWatch.is_active.is_(True),
            ConvectiveWatch.centroid.isnot(None),
            ST_DWithin(ConvectiveWatch.centroid, point, radius_m),
        )
        .order_by("distance_m")
        .limit(limit)
    )
    return [(watch, dist_m / 1000.0) for watch, dist_m in result.all()]
