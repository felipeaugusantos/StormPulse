"""Alert read endpoints (authenticated, tenant+user scoped)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.alerts.schemas import AlertOut
from app.api.deps import get_current_user, get_db
from app.users.models import User

router = APIRouter(tags=["alerts"])

# The alerts feed is "what needs attention now", not a permanent audit log
# (that already exists — every Alert row stays in the database forever,
# this only bounds what the dashboard surfaces). Without this, an old,
# already-resolved event (e.g. a satellite watch's own DISSIPATED alert)
# stayed in the last-50 feed indefinitely, reading as still relevant days
# later — reported live in production 2026-08-27.
_DEFAULT_ALERTS_WINDOW_HOURS = 24


@router.get("", response_model=list[AlertOut], summary="Alertas do usuário")
async def list_alerts(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    window_hours: int = Query(default=_DEFAULT_ALERTS_WINDOW_HOURS, ge=1, le=720),
) -> object:
    cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
    result = await session.execute(
        select(Alert)
        .where(
            Alert.tenant_id == user.tenant_id,
            Alert.user_id == user.id,
            Alert.created_at >= cutoff,
        )
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
