"""Public (unauthenticated) read-only endpoints — "visitor mode" (FASE 15).

No personalized data (locations, risk) is ever exposed here — only storm
cells (already tenant-agnostic global data, see ``storms/service.py``) and
official warnings, fetched live from the active weather provider per point
(no persistence — see ADR-0008 for why).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import Settings, get_settings
from app.satellite import service as satellite_service
from app.satellite.schemas import ConvectiveWatchOut
from app.storms import service as storm_service
from app.storms.schemas import NearbyStormCellOut, StormCellOut
from app.weather.factory import get_weather_provider
from app.weather.provider import Warning

router = APIRouter(tags=["public"])


@router.get("/storms", response_model=list[StormCellOut], summary="Células recentes (público)")
async def public_storms(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> object:
    return await storm_service.list_recent_cells(session, limit=limit)


@router.get(
    "/storms/nearby",
    response_model=list[NearbyStormCellOut],
    summary="Células próximas de um ponto (público, ST_DWithin)",
)
async def public_storms_nearby(
    session: AsyncSession = Depends(get_db),
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50.0, gt=0, le=500),
) -> list[NearbyStormCellOut]:
    pairs = await storm_service.cells_within_radius(
        session, latitude=lat, longitude=lon, radius_km=radius_km
    )
    return [
        NearbyStormCellOut(
            **StormCellOut.model_validate(cell).model_dump(),
            distance_km=round(dist, 2),
        )
        for cell, dist in pairs
    ]


@router.get(
    "/satellite/watches",
    response_model=list[ConvectiveWatchOut],
    summary="Observações via satélite ativas (público)",
)
async def public_satellite_watches(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> object:
    return await satellite_service.list_active_watches(session, limit=limit)


@router.get(
    "/warnings",
    response_model=list[Warning],
    summary="Avisos oficiais ativos perto de um ponto (público, ao vivo)",
)
async def public_warnings(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    settings: Settings = Depends(get_settings),
) -> list[Warning]:
    provider = get_weather_provider(settings)
    return await provider.get_warnings(lat, lon)
