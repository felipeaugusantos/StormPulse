"""Read queries for lightning strikes — same shape as satellite/service.py."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lightning.models import LightningStrike

# How many recent strikes the bounding-box pre-filter considers before the
# exact Haversine check below — generous relative to any single radius
# query's expected result size, cheap enough not to matter.
_CANDIDATE_POOL_SIZE = 2000


async def list_recent_strikes(session: AsyncSession, *, limit: int = 1000) -> list[LightningStrike]:
    result = await session.execute(
        select(LightningStrike).order_by(LightningStrike.detected_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return earth_radius_km * 2 * math.asin(math.sqrt(a))


async def strikes_within_radius(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    limit: int = 500,
) -> list[tuple[LightningStrike, float]]:
    """Return (strike, distance_km) for recent strikes within radius.

    Unlike storms/convective watches, this table has no PostGIS geometry
    column — just raw lat/lon floats — so there's no `ST_DWithin` to lean
    on. A cheap bounding-box pre-filter in SQL narrows the candidate set
    (degrees-per-km is only approximate, so it's intentionally generous),
    then exact Haversine distance is computed in Python for the real
    radius check and sort.
    """
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(latitude)), 0.01))
    result = await session.execute(
        select(LightningStrike)
        .where(
            LightningStrike.latitude.between(latitude - lat_delta, latitude + lat_delta),
            LightningStrike.longitude.between(longitude - lon_delta, longitude + lon_delta),
        )
        .order_by(LightningStrike.detected_at.desc())
        .limit(_CANDIDATE_POOL_SIZE)
    )
    scored = [
        (strike, _haversine_km(latitude, longitude, strike.latitude, strike.longitude))
        for strike in result.scalars().all()
    ]
    nearby = sorted((pair for pair in scored if pair[1] <= radius_km), key=lambda pair: pair[1])
    return nearby[:limit]
