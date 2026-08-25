"""Authentication domain logic: registration and credential verification."""

from __future__ import annotations

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import RegisterIn
from app.core.crypto import blind_index
from app.core.enums import UserRole
from app.core.rls import bypass_rls, set_tenant_context
from app.core.security import hash_password, verify_password
from app.tenants.models import Tenant
from app.users.models import User


class EmailAlreadyRegistered(Exception):
    """Raised when registering an email that already exists."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


async def _email_exists(session: AsyncSession, email: str) -> bool:
    # Every function in this module runs *before* a tenant is known — email
    # uniqueness and login lookups are inherently cross-tenant (an email
    # isn't scoped to one tenant), so RLS (migration 0b7b9a5dbd11) would
    # otherwise fail every one of them closed.
    await bypass_rls(session)
    result = await session.execute(select(User.id).where(User.email_index == blind_index(email)))
    return result.first() is not None


async def _create_tenant_and_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str | None,
    hashed_password: str,
    google_sub: str | None,
    tenant_name: str | None,
    storm_module: bool = True,
    agro_module: bool = False,
) -> User:
    """Create a personal tenant and its first (USER) account.

    The first user of a freshly-created tenant is a plain USER; elevating to
    ADMIN is an explicit administrative action (later phase), never something a
    self-registration (password or Google) can grant.
    """
    await bypass_rls(session)
    base = tenant_name or email.split("@", 1)[0]
    tenant = Tenant(
        name=tenant_name or f"{base} (pessoal)",
        slug=f"{_slugify(base)}-{uuid.uuid4().hex[:8]}",
        storm_enabled=storm_module,
        agro_enabled=agro_module,
    )
    session.add(tenant)
    await session.flush()  # assigns tenant.id

    user = User(
        tenant_id=tenant.id,
        email=email,
        email_index=blind_index(email),
        full_name=full_name,
        hashed_password=hashed_password,
        google_sub=google_sub,
        google_sub_index=blind_index(google_sub) if google_sub is not None else None,
        role=UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    # `commit()` ends the transaction `bypass_rls` above was scoped to —
    # the refresh below is a fresh SELECT in a new transaction, so it
    # needs its own GUC. Now that `tenant.id` is known, scope to it
    # precisely rather than bypassing again.
    await set_tenant_context(session, tenant.id)
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
        storm_module=data.storm_module,
        agro_module=data.agro_module,
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
    await bypass_rls(session)

    result = await session.execute(
        select(User).where(User.google_sub_index == blind_index(google_sub))
    )
    user = result.scalar_one_or_none()
    if user is not None:
        return user if user.is_active else None

    result = await session.execute(select(User).where(User.email_index == blind_index(email)))
    user = result.scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            return None
        user.google_sub = google_sub
        user.google_sub_index = blind_index(google_sub)
        await session.commit()
        # Same post-commit GUC loss as in `_create_tenant_and_user` above.
        await set_tenant_context(session, user.tenant_id)
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
    await bypass_rls(session)
    result = await session.execute(
        select(User).where(User.email_index == blind_index(email.lower()))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
