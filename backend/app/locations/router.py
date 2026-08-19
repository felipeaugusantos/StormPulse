"""Location CRUD endpoints (tenant + user scoped)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.locations import service
from app.locations.models import Location
from app.locations.schemas import LocationCreate, LocationOut, LocationUpdate
from app.storms import service as storm_service
from app.storms.schemas import StormRiskOut
from app.users.models import User

router = APIRouter(tags=["locations"])


async def _get_owned_or_404(session: AsyncSession, user: User, location_id: uuid.UUID) -> Location:
    location = await service.get_location(session, user, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")
    return location


@router.post(
    "",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Criar local monitorado",
)
async def create_location(
    data: LocationCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    return await service.create_location(session, user, data)


@router.get("", response_model=list[LocationOut], summary="Listar locais do usuário")
async def list_locations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Location]:
    return await service.list_locations(session, user)


@router.get("/{location_id}", response_model=LocationOut, summary="Detalhar local")
async def get_location(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    return await _get_owned_or_404(session, user, location_id)


@router.put("/{location_id}", response_model=LocationOut, summary="Atualizar local")
async def update_location(
    location_id: uuid.UUID,
    data: LocationUpdate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    location = await _get_owned_or_404(session, user, location_id)
    return await service.update_location(session, location, data)


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover local",
)
async def delete_location(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    location = await _get_owned_or_404(session, user, location_id)
    await service.delete_location(session, location)


@router.get(
    "/{location_id}/risk",
    response_model=StormRiskOut,
    summary="Última avaliação de risco do local",
)
async def get_location_risk(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> object:
    location = await _get_owned_or_404(session, user, location_id)
    risk = await storm_service.latest_risk_for_location(session, location.id)
    if risk is None:
        # Honest 404: no risk has been computed yet (needs the storm engine).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma avaliação de risco disponível para este local ainda",
        )
    return risk
