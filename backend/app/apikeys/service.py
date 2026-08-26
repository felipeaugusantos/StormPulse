"""API key lifecycle: create, list, revoke (item 1, ADR-0062)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys.models import ApiKey
from app.core.rls import bypass_rls, set_tenant_context
from app.users.models import User

# Prefix identifies StormPulse keys at a glance (same idea as Stripe's
# `sk_live_`/GitHub's `ghp_`) — not a secret itself, safe to log/display.
_KEY_PREFIX = "sp_live_"
_KEY_RANDOM_BYTES = 32


class ApiKeyNotFound(Exception):
    """The target key doesn't exist, or doesn't belong to this user."""


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def create_api_key(session: AsyncSession, *, user: User, name: str) -> tuple[ApiKey, str]:
    """Returns the new row and the raw key — the raw value is never
    recoverable again after this call returns; only its hash is stored."""
    raw_key = _KEY_PREFIX + secrets.token_urlsafe(_KEY_RANDOM_BYTES)
    key = ApiKey(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=name,
        key_prefix=raw_key[: len(_KEY_PREFIX) + 4],
        key_hash=_hash_key(raw_key),
    )
    session.add(key)
    await session.commit()
    # commit() ends the transaction the caller's tenant context (SET
    # LOCAL, from get_current_user) was scoped to — re-apply before the
    # post-commit refresh, same reasoning as auth.service._create_tenant_and_user.
    await set_tenant_context(session, user.tenant_id)
    await session.refresh(key)
    return key, raw_key


async def list_api_keys(session: AsyncSession, *, user: User) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(session: AsyncSession, *, user: User, key_id: uuid.UUID) -> None:
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise ApiKeyNotFound(key_id)
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await session.commit()


async def resolve_api_key(session: AsyncSession, raw_key: str) -> ApiKey | None:
    """Looks up an active key by its raw value — cross-tenant by nature
    (the tenant isn't known until the key resolves to one), same reasoning
    as `auth.service.authenticate`'s email lookup. Returns `None` for an
    unknown, revoked key. Stamps `last_used_at` best-effort on every
    successful resolution."""
    await bypass_rls(session)
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == _hash_key(raw_key)))
    key = result.scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    key.last_used_at = datetime.now(UTC)
    await session.commit()
    return key
