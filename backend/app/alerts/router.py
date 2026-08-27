"""Alert read endpoints (authenticated, tenant+user scoped)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.alerts.schemas import AlertOut
from app.api.deps import get_current_user, get_db
from app.core.enums import AlertEventType
from app.users.models import User

router = APIRouter(tags=["alerts"])

# The alerts feed is "what needs attention now", not a permanent audit log
# (that already exists — every Alert row stays in the database forever,
# this only bounds what the dashboard surfaces). Without this, an old,
# already-resolved event (e.g. a satellite watch's own DISSIPATED alert)
# stayed in the last-50 feed indefinitely, reading as still relevant days
# later — reported live in production 2026-08-27.
_DEFAULT_ALERTS_WINDOW_HOURS = 24

# Satellite watches are the fastest-changing signal in the system (10-min
# detection cadence) — even within the general 24h window, both halves of
# a watch's story go stale within hours, reported live in production
# 2026-08-27 (a 16h-old "detected" and a 12h-old "dissipated" alert for
# the same watch both still reading as current). Two follow-up rules,
# independent of the caller's own `window_hours` (that param is a
# reasonable request for more/less of the *normal* feed, not license to
# resurrect a watch that already dissipated):
# - Once a watch dissipates, its own DETECTED alert is superseded — the
#   watch's current state is "not there anymore", not "spotted".
# - A DISSIPATED alert is itself only "still relevant" briefly — this
#   fixed window is deliberately shorter than the general one.
_SATELLITE_DISSIPATED_WINDOW_HOURS = 3


@router.get("", response_model=list[AlertOut], summary="Alertas do usuário")
async def list_alerts(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=200),
    window_hours: int = Query(default=_DEFAULT_ALERTS_WINDOW_HOURS, ge=1, le=720),
) -> object:
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=window_hours)
    dissipated_cutoff = now - timedelta(hours=_SATELLITE_DISSIPATED_WINDOW_HOURS)

    dissipated_watch_ids = select(Alert.convective_watch_id).where(
        Alert.tenant_id == user.tenant_id,
        Alert.user_id == user.id,
        Alert.event_type == AlertEventType.SATELLITE_WATCH_DISSIPATED,
    )

    result = await session.execute(
        select(Alert)
        .where(
            Alert.tenant_id == user.tenant_id,
            Alert.user_id == user.id,
            Alert.created_at >= cutoff,
            not_(
                and_(
                    Alert.event_type == AlertEventType.SATELLITE_WATCH_DETECTED,
                    Alert.convective_watch_id.in_(dissipated_watch_ids),
                )
            ),
            not_(
                and_(
                    Alert.event_type == AlertEventType.SATELLITE_WATCH_DISSIPATED,
                    Alert.created_at < dissipated_cutoff,
                )
            ),
        )
        .order_by(Alert.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
