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
from sqlalchemy.orm import selectinload

from app.storms.models import StormCell, StormObservation, StormRisk, StormTrack
from app.storms.schemas import StormCellOut
from engine.geo import destination_point

_CELL_LOAD_OPTIONS = (selectinload(StormCell.tracks).selectinload(StormTrack.observations),)

# Straight-line extrapolation horizon for "where the cell would be next" —
# matches the product ask (1h ahead), not a physical constant.
_PROJECTION_HOURS = 1.0


def _point(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def _latest_active_observation(cell: StormCell) -> StormObservation | None:
    """Most recent observation among the cell's still-active tracks.

    A dissipated (inactive) track's last known motion is stale — never used
    to project a "where it's headed" position for a storm that's gone.
    """
    candidates = [obs for track in cell.tracks if track.is_active for obs in track.observations]
    if not candidates:
        return None
    return max(candidates, key=lambda o: o.observed_at)


def to_storm_cell_out(cell: StormCell) -> StormCellOut:
    """Builds the API shape, adding the latest track's motion and a 1h
    straight-line projection (engine/trajectory/estimator.py computes
    speed_kmh/direction_deg per observation; this reuses that stored value
    rather than recomputing it). ``None`` when there's no active track with
    a computed trajectory yet — never a fabricated estimate."""
    out = StormCellOut.model_validate(cell)
    obs = _latest_active_observation(cell)
    if obs is None or obs.speed_kmh is None or obs.direction_deg is None:
        return out
    distance_km = obs.speed_kmh * _PROJECTION_HOURS
    proj_lat, proj_lon = destination_point(
        obs.latitude, obs.longitude, obs.direction_deg, distance_km
    )
    return out.model_copy(
        update={
            "speed_kmh": obs.speed_kmh,
            "direction_deg": obs.direction_deg,
            "projected_latitude_1h": proj_lat,
            "projected_longitude_1h": proj_lon,
        }
    )


async def list_recent_cells(session: AsyncSession, *, limit: int = 100) -> list[StormCell]:
    result = await session.execute(
        select(StormCell)
        .options(*_CELL_LOAD_OPTIONS)
        .order_by(StormCell.detected_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_cell(session: AsyncSession, cell_id: uuid.UUID) -> StormCell | None:
    result = await session.execute(
        select(StormCell).options(*_CELL_LOAD_OPTIONS).where(StormCell.id == cell_id)
    )
    return result.scalar_one_or_none()


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
        .options(*_CELL_LOAD_OPTIONS)
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
