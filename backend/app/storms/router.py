"""Storm read endpoints (authenticated)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.storms import service
from app.storms.schemas import NearbyStormCellOut, StormCellOut
from app.users.models import User

router = APIRouter(tags=["storms"])


@router.get("", response_model=list[StormCellOut], summary="Células recentes")
async def list_storms(
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[StormCellOut]:
    cells = await service.list_recent_cells(session, limit=limit)
    return [service.to_storm_cell_out(cell) for cell in cells]


@router.get(
    "/nearby",
    response_model=list[NearbyStormCellOut],
    summary="Células próximas de um ponto (ST_DWithin)",
)
async def storms_nearby(
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=50.0, gt=0, le=500),
) -> list[NearbyStormCellOut]:
    pairs = await service.cells_within_radius(
        session, latitude=lat, longitude=lon, radius_km=radius_km
    )
    return [
        NearbyStormCellOut(
            **service.to_storm_cell_out(cell).model_dump(),
            distance_km=round(dist, 2),
        )
        for cell, dist in pairs
    ]


@router.get("/{cell_id}", response_model=StormCellOut, summary="Detalhar célula")
async def get_storm(
    cell_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StormCellOut:
    cell = await service.get_cell(session, cell_id)
    if cell is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Célula não encontrada")
    return service.to_storm_cell_out(cell)
