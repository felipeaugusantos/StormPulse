"""Authentication domain logic: registration and credential verification."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import RegisterIn
from app.core.enums import UserRole
from app.core.security import hash_password, verify_password
from app.tenants.models import Tenant
from app.users.models import User


class EmailAlreadyRegistered(Exception):
    """Raised when registering an email that already exists."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


async def _email_exists(session: AsyncSession, email: str) -> bool:
    result = await session.execute(select(User.id).where(User.email == email))
    return result.first() is not None


async def register_user(session: AsyncSession, data: RegisterIn) -> User:
    """Create a personal tenant and its first (USER) account.

    The first user of a freshly-created tenant is a plain USER; elevating to
    ADMIN is an explicit administrative action (later phase), never something a
    self-registration can grant.
    """
    email = data.email.lower()
    if await _email_exists(session, email):
        raise EmailAlreadyRegistered(email)

    base = data.tenant_name or email.split("@", 1)[0]
    tenant = Tenant(
        name=data.tenant_name or f"{base} (pessoal)",
        slug=f"{_slugify(base)}-{uuid.uuid4().hex[:8]}",
    )
    session.add(tenant)
    await session.flush()  # assigns tenant.id

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        role=UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active."""
    result = await session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
