"""Cross-tenant read queries and mutations for the platform-admin panel
(FASE 28, ADR-0048/ADR-0049).

Every mutation writes its own `AdminAuditLog` row in the same transaction
it makes the change in — there is no code path that mutates a user without
also recording who did it and what changed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import AdminAuditLog
from app.admin.schemas import (
    AdminAuditLogOut,
    AdminStatsOut,
    AdminTenantOut,
    AdminUserOut,
    AdminUserUpdateIn,
)
from app.alerts.models import Alert
from app.core.enums import UserRole
from app.core.rls import bypass_rls
from app.locations.models import Location
from app.tenants.models import Tenant
from app.users.models import User

MAX_PAGE_SIZE = 200

# Only these two roles are actually implemented today (METEOROLOGIST/
# COMPANY_ADMIN/OPERATOR are reserved for later phases, per
# app/core/enums.py) — granting a role nothing in the app understands yet
# would be a silent no-op dressed up as a real permission change.
ALLOWED_ROLE_CHANGES = {UserRole.USER, UserRole.ADMIN}


class UserNotFound(Exception):
    """The target `user_id` doesn't exist."""


class NoChangesRequested(Exception):
    """Neither `is_active` nor `role` was set on the update."""


class UnsupportedRole(Exception):
    """The requested role isn't one of ALLOWED_ROLE_CHANGES."""

    def __init__(self, role: UserRole) -> None:
        self.role = role


class SelfLockoutAttempt(Exception):
    """An operator tried to deactivate their own account."""


async def list_users(
    session: AsyncSession, *, search: str | None, limit: int, offset: int
) -> tuple[list[AdminUserOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    stmt = select(User, Tenant.name).join(Tenant, Tenant.id == User.tenant_id)
    stmt = stmt.order_by(User.created_at.desc())

    rows: Sequence[tuple[User, str]]
    if search:
        # email/full_name are encrypted at rest (ADR-0055) — a random AES-GCM
        # nonce per row means the ciphertext can never be filtered with SQL
        # LIKE, so this decrypts (via the ORM's transparent EncryptedString)
        # and filters in Python instead, then paginates the filtered list.
        # Acceptable at this platform's admin-panel scale; would need a
        # dedicated search index if the user base grew far larger.
        needle = search.lower()
        all_rows = (await session.execute(stmt)).all()
        matched = [
            (user, tenant_name)
            for user, tenant_name in all_rows
            if needle in user.email.lower() or (user.full_name and needle in user.full_name.lower())
        ]
        total = len(matched)
        rows = matched[offset : offset + limit]
    else:
        total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        rows = [
            (user, tenant_name)
            for user, tenant_name in (await session.execute(stmt.limit(limit).offset(offset))).all()
        ]

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
            last_login_at=user.last_login_at,
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


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> AdminUserOut | None:
    stmt = (
        select(User, Tenant.name)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == user_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    user, tenant_name = row
    return AdminUserOut(
        id=user.id,
        tenant_id=user.tenant_id,
        tenant_name=tenant_name,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _log(*, actor: User, action: str, target: User, detail: dict[str, object]) -> AdminAuditLog:
    return AdminAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_user_id=target.id,
        target_email=target.email,
        detail=detail,
    )


async def update_user(
    session: AsyncSession, *, actor: User, target_user_id: uuid.UUID, data: AdminUserUpdateIn
) -> AdminUserOut:
    """Applies `is_active`/`role` changes and writes one audit log row per
    field that actually changed value (a no-op field — e.g. re-sending the
    role it already has — writes nothing, since nothing happened)."""
    if data.is_active is None and data.role is None:
        raise NoChangesRequested
    if data.role is not None and data.role not in ALLOWED_ROLE_CHANGES:
        raise UnsupportedRole(data.role)

    target = await session.get(User, target_user_id)
    if target is None:
        raise UserNotFound(target_user_id)

    if data.is_active is False and target.id == actor.id:
        raise SelfLockoutAttempt

    if data.is_active is not None and data.is_active != target.is_active:
        session.add(
            _log(
                actor=actor,
                action="user.activate" if data.is_active else "user.deactivate",
                target=target,
                detail={"is_active": {"from": target.is_active, "to": data.is_active}},
            )
        )
        target.is_active = data.is_active

    if data.role is not None and data.role != target.role:
        session.add(
            _log(
                actor=actor,
                action="user.role_change",
                target=target,
                detail={"role": {"from": target.role.value, "to": data.role.value}},
            )
        )
        target.role = data.role

    await session.commit()
    # commit() ends the transaction require_platform_admin's bypass was
    # scoped to (RLS, migration 0b7b9a5dbd11) — re-apply before the
    # post-commit re-fetch, which is legitimately cross-tenant (target may
    # belong to a different tenant than the acting admin).
    await bypass_rls(session)

    updated = await get_user(session, target_user_id)
    assert updated is not None  # the row we just updated can't have vanished
    return updated


async def list_audit_log(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[AdminAuditLogOut], int]:
    limit = min(limit, MAX_PAGE_SIZE)
    total = (await session.execute(select(func.count()).select_from(AdminAuditLog))).scalar_one()
    stmt = (
        select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit).offset(offset)
    )
    rows = (await session.execute(stmt)).scalars().all()
    items = [AdminAuditLogOut.model_validate(row) for row in rows]
    return items, total


async def get_stats(session: AsyncSession) -> AdminStatsOut:
    now = datetime.now(UTC)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    total_tenants = (await session.execute(select(func.count()).select_from(Tenant))).scalar_one()
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    active_users_7d = (
        await session.execute(
            select(func.count()).select_from(User).where(User.last_login_at >= cutoff_7d)
        )
    ).scalar_one()
    active_users_30d = (
        await session.execute(
            select(func.count()).select_from(User).where(User.last_login_at >= cutoff_30d)
        )
    ).scalar_one()
    total_locations = (
        await session.execute(select(func.count()).select_from(Location))
    ).scalar_one()
    alerts_last_30d = (
        await session.execute(
            select(func.count()).select_from(Alert).where(Alert.created_at >= cutoff_30d)
        )
    ).scalar_one()

    return AdminStatsOut(
        total_tenants=total_tenants,
        total_users=total_users,
        active_users_7d=active_users_7d,
        active_users_30d=active_users_30d,
        total_locations=total_locations,
        alerts_last_30d=alerts_last_30d,
    )
