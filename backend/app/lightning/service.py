"""Read queries for lightning strikes — same shape as satellite/service.py."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lightning.models import LightningStrike


async def list_recent_strikes(session: AsyncSession, *, limit: int = 1000) -> list[LightningStrike]:
    result = await session.execute(
        select(LightningStrike).order_by(LightningStrike.detected_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
