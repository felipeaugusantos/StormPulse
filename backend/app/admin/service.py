"""Cross-tenant read queries for the platform-admin panel (FASE 28, ADR-0048).

Deliberately read-only in this first phase — listing tenants/users. Any
mutation (deactivate account, promote a role, etc.) is a later phase, with
its own audit trail.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import AdminTenantOut, AdminUserOut
from app.locations.models import Location
from app.tenants.models import Tenant
from app.users.models import User

MAX_PAGE_SIZE = 200


async def list_users(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[AdminUserOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    stmt = select(User, Tenant.name).join(Tenant, Tenant.id == User.tenant_id)
    count_stmt = select(func.count()).select_from(User)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(User.email).like(pattern))
        count_stmt = count_stmt.where(func.lower(User.email).like(pattern))

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [
        AdminUserOut(
            id=user.id,
            tenant_id=user.tenant_id,
            tenant_name=tenant_name,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_platform_admin=user.is_platform_admin,
            created_at=user.created_at,
        )
        for user, tenant_name in rows
    ]
    return items, total


async def list_tenants(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[AdminTenantOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    user_counts = (
        select(User.tenant_id, func.count().label("user_count")).group_by(User.tenant_id).subquery()
    )
    location_counts = (
        select(Location.tenant_id, func.count().label("location_count"))
        .group_by(Location.tenant_id)
        .subquery()
    )
    stmt = (
        select(
            Tenant,
            func.coalesce(user_counts.c.user_count, 0),
            func.coalesce(location_counts.c.location_count, 0),
        )
        .outerjoin(user_counts, user_counts.c.tenant_id == Tenant.id)
        .outerjoin(location_counts, location_counts.c.tenant_id == Tenant.id)
    )
    count_stmt = select(func.count()).select_from(Tenant)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(func.lower(Tenant.name).like(pattern))
        count_stmt = count_stmt.where(func.lower(Tenant.name).like(pattern))

    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    items = [
        AdminTenantOut(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            user_count=user_count,
            location_count=location_count,
        )
        for tenant, user_count, location_count in rows
    ]
    return items, total
