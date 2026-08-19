"""Alert read endpoints (authenticated, tenant+user scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.alerts.schemas import AlertOut
from app.api.deps import get_current_user, get_db
from app.users.models import User

router = APIRouter(tags=["alerts"])


@router.get("", response_model=list[AlertOut], summary="Alertas do usuário")
async def list_alerts(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
) -> object:
    result = await session.execute(
        select(Alert)
        .where(Alert.tenant_id == user.tenant_id, Alert.user_id == user.id)
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
