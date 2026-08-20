"""Convective watch read endpoints (authenticated) — FASE 16."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.satellite import service
from app.satellite.schemas import ConvectiveWatchOut, NearbyConvectiveWatchOut
from app.users.models import User

router = APIRouter(tags=["satellite"])


@router.get("", response_model=list[ConvectiveWatchOut], summary="Observações via satélite ativas")
async def list_watches(
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
) -> object:
    return await service.list_active_watches(session, limit=limit)


@router.get(
    "/nearby",
    response_model=list[NearbyConvectiveWatchOut],
    summary="Observações via satélite próximas de um ponto (ST_DWithin)",
)
async def watches_nearby(
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50.0, gt=0, le=500),
) -> list[NearbyConvectiveWatchOut]:
    pairs = await service.watches_within_radius(
        session, latitude=lat, longitude=lon, radius_km=radius_km
    )
    return [
        NearbyConvectiveWatchOut(
            **ConvectiveWatchOut.model_validate(watch).model_dump(),
            distance_km=round(dist, 2),
        )
        for watch, dist in pairs
    ]
