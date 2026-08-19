"""Authentication domain logic: registration and credential verification."""

from __future__ import annotations

import re
import secrets
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


async def _create_tenant_and_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str | None,
    hashed_password: str,
    google_sub: str | None,
    tenant_name: str | None,
) -> User:
    """Create a personal tenant and its first (USER) account.

    The first user of a freshly-created tenant is a plain USER; elevating to
    ADMIN is an explicit administrative action (later phase), never something a
    self-registration (password or Google) can grant.
    """
    base = tenant_name or email.split("@", 1)[0]
    tenant = Tenant(
        name=tenant_name or f"{base} (pessoal)",
        slug=f"{_slugify(base)}-{uuid.uuid4().hex[:8]}",
    )
    session.add(tenant)
    await session.flush()  # assigns tenant.id

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=full_name,
        hashed_password=hashed_password,
        google_sub=google_sub,
        role=UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def register_user(session: AsyncSession, data: RegisterIn) -> User:
    email = data.email.lower()
    if await _email_exists(session, email):
        raise EmailAlreadyRegistered(email)
    return await _create_tenant_and_user(
        session,
        email=email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        google_sub=None,
        tenant_name=data.tenant_name,
    )


async def authenticate_google(
    session: AsyncSession, *, google_sub: str, email: str, full_name: str | None
) -> User | None:
    """Return the user for a verified Google sign-in, creating/linking as needed.

    Lookup order: existing ``google_sub`` first (stable across e-mail
    changes), then existing e-mail (links the Google account to a password
    account created earlier with the same address), then a brand-new
    tenant+account. Password-less (Google-only) accounts get a random,
    unusable hash — ``hashed_password`` stays ``NOT NULL`` without
    special-casing ``None`` through the auth code (see ADR-0008).

    Returns ``None`` for a deactivated existing account (mirrors
    ``authenticate``) — a disabled account can't come back via Google either.
    """
    email = email.lower()

    result = await session.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is not None:
        return user if user.is_active else None

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            return None
        user.google_sub = google_sub
        await session.commit()
        await session.refresh(user)
        return user

    return await _create_tenant_and_user(
        session,
        email=email,
        full_name=full_name,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        google_sub=google_sub,
        tenant_name=None,
    )


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active."""
    result = await session.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
