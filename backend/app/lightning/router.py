"""Lightning strike read endpoints (authenticated) — FASE 23."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.lightning import service
from app.lightning.schemas import LightningStrikeOut
from app.users.models import User

router = APIRouter(tags=["lightning"])


@router.get("", response_model=list[LightningStrikeOut], summary="Raios recentes")
async def list_strikes(
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> object:
    return await service.list_recent_strikes(session, limit=limit)
