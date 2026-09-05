from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.locations.models import Location
from app.organizations.models import LocationAccessGrant
from app.users.models import User

MANAGER_ROLES = {UserRole.OWNER, UserRole.ADMIN, UserRole.USER, UserRole.COMPANY_ADMIN}
WRITE_ROLES = MANAGER_ROLES | {UserRole.AGRONOMIST, UserRole.OPERATOR, UserRole.METEOROLOGIST}


def can_manage_members(user: User) -> bool:
    return user.role in MANAGER_ROLES


def can_write(user: User) -> bool:
    return user.role in WRITE_ROLES


def membership_active(user: User) -> bool:
    expiry = user.access_expires_at
    return expiry is None or expiry > datetime.now(UTC)


async def can_access_location(session: AsyncSession, user: User, location: Location) -> bool:
    if location.tenant_id != user.tenant_id or not membership_active(user):
        return False
    if user.organization_wide_access:
        return True
    now = datetime.now(UTC)
    allowed_ids = [location.id]
    if location.parent_location_id is not None:
        allowed_ids.append(location.parent_location_id)
    return (
        await session.scalar(
            select(LocationAccessGrant.id).where(
                LocationAccessGrant.user_id == user.id,
                LocationAccessGrant.location_id.in_(allowed_ids),
                LocationAccessGrant.revoked_at.is_(None),
                or_(LocationAccessGrant.expires_at.is_(None), LocationAccessGrant.expires_at > now),
            )
        )
        is not None
    )
