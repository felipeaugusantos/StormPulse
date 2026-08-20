"""User account operations (self-service — LGPD deletion, FASE 22)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenants.models import Tenant
from app.users.models import User


async def delete_own_account(session: AsyncSession, user: User) -> None:
    """Delete a user's account and all data they own.

    A tenant isn't guaranteed 1:1 with a user (Google account-linking can
    attach a second user to an existing tenant later) — only delete the
    tenant itself if this was its last remaining user, otherwise deleting it
    would take other users' data down too. Locations, alerts, notifications
    and reports all cascade via ``ondelete=CASCADE`` on their ``user_id``/
    ``location_id`` FKs, so deleting the ``User`` row is enough on its own.
    """
    result = await session.execute(
        select(func.count(User.id)).where(User.tenant_id == user.tenant_id)
    )
    other_members = result.scalar_one() - 1

    if other_members == 0:
        tenant = await session.get(Tenant, user.tenant_id)
        if tenant is not None:
            await session.delete(tenant)  # cascades to the user via tenant_id FK
    else:
        await session.delete(user)

    await session.commit()
