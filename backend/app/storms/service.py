"""Storm read queries, including PostGIS proximity search.

Proximity uses ``ST_DWithin`` on the ``geography`` centroid so the radius is in
metres on the WGS84 spheroid (no manual haversine). Until the storm engine
(FASE 6+) populates cells, these queries correctly return empty results — never
fabricated storms.
"""

from __future__ import annotations

import uuid

from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import ST_Distance, ST_DWithin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storms.models import StormCell, StormRisk


def _point(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


async def list_recent_cells(session: AsyncSession, *, limit: int = 100) -> list[StormCell]:
    result = await session.execute(
        select(StormCell).order_by(StormCell.detected_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_cell(session: AsyncSession, cell_id: uuid.UUID) -> StormCell | None:
    return await session.get(StormCell, cell_id)


async def cells_within_radius(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    limit: int = 100,
) -> list[tuple[StormCell, float]]:
    """Return (cell, distance_km) for cells whose centroid is within radius."""
    point = _point(latitude, longitude)
    radius_m = radius_km * 1000.0
    distance_m = ST_Distance(StormCell.centroid, point)

    result = await session.execute(
        select(StormCell, distance_m.label("distance_m"))
        .where(
            StormCell.centroid.isnot(None),
            ST_DWithin(StormCell.centroid, point, radius_m),
        )
        .order_by("distance_m")
        .limit(limit)
    )
    return [(cell, dist_m / 1000.0) for cell, dist_m in result.all()]


async def latest_risk_for_location(
    session: AsyncSession, location_id: uuid.UUID
) -> StormRisk | None:
    result = await session.execute(
        select(StormRisk)
        .where(StormRisk.location_id == location_id)
        .order_by(StormRisk.computed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
