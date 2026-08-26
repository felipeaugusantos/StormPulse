"""External/public API (item 1, ADR-0062) — read-only access to a
tenant's own data for third-party integration, authenticated by an
`X-API-Key` header (`require_api_key`, see `app/api/deps.py`) instead of
the dashboard's Bearer JWT.

Deliberately reuses the exact same service-layer functions the
dashboard's own routes call (`locations.service`, `storms.service`) —
this is the same data through a different door, never a parallel
implementation that could drift from it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.alerts.schemas import AlertOut
from app.api.deps import get_db, require_api_key
from app.locations import service as location_service
from app.locations.schemas import LocationOut
from app.storms import service as storm_service
from app.storms.schemas import StormRiskOut
from app.users.models import User

router = APIRouter(tags=["external-api"])


@router.get(
    "/locations",
    response_model=list[LocationOut],
    summary="Locais monitorados pela conta dona da chave de API",
)
async def list_locations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_key),
) -> list[LocationOut]:
    locations = await location_service.list_locations(session, user)
    return [LocationOut.model_validate(loc) for loc in locations]


@router.get(
    "/locations/{location_id}/risk",
    response_model=StormRiskOut,
    summary="Última avaliação de risco de um local (mesmo dado do painel)",
)
async def get_location_risk(
    location_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_key),
) -> StormRiskOut:
    location = await location_service.get_location(session, user, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Local não encontrado")
    risk = await storm_service.latest_risk_for_location(session, location.id)
    if risk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhuma avaliação de risco disponível para este local ainda",
        )
    return StormRiskOut.model_validate(risk)


@router.get(
    "/alerts",
    response_model=list[AlertOut],
    summary="Alertas mais recentes da conta dona da chave de API",
)
async def list_alerts(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_api_key),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AlertOut]:
    result = await session.execute(
        select(Alert)
        .where(Alert.tenant_id == user.tenant_id, Alert.user_id == user.id)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
    return [AlertOut.model_validate(a) for a in result.scalars().all()]
