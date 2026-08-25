"""FastAPI dependencies: DB session, current user and RBAC guards."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.enums import UserRole
from app.core.rls import bypass_rls, set_tenant_context
from app.core.security import TokenError, decode_token
from app.users.models import User

_bearer = HTTPBearer(auto_error=False)


def get_request_settings(request: Request) -> Settings:
    """The ``Settings`` instance this app was actually built with.

    Unlike ``Depends(get_settings)`` (process-wide ``lru_cache``, frozen at
    first call), this reflects whatever ``Settings`` was passed to
    ``create_app()`` for *this* app instance — needed wherever a value must
    vary per-app-instance within the same process (e.g. tests exercising two
    different configs). See ADR-0007/0008 for the ``get_settings()`` caching
    gotcha this works around.
    """
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async DB session from the app's session factory."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> User:
    """Resolve the authenticated user from a Bearer access token.

    Row-level security (migration ``0b7b9a5dbd11``) protects every
    tenant-scoped table, including ``users`` itself — but the lookup below
    is exactly how a request's tenant gets known in the first place, so it
    can't be filtered by a tenant GUC that doesn't exist yet. The JWT's
    signature already authenticates *which* row this is allowed to read
    (``user_id`` came from a token this server issued), so bypass is safe
    here specifically. It's narrowed back off immediately after, replaced
    with the real tenant, before any other query runs in this request.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Não autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials, settings, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError) as exc:
        raise unauthorized from exc

    await bypass_rls(session)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    await set_tenant_context(session, user.tenant_id)
    await session.execute(text("SET LOCAL app.bypass_rls = 'off'"))
    return user


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory enforcing that the current user has one of ``roles``."""

    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissão insuficiente",
            )
        return current_user

    return _guard


# Convenience guard used by admin-only endpoints in later phases.
require_admin = require_roles(UserRole.ADMIN)


async def require_platform_admin(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Cross-tenant guard (FASE 28, ADR-0048) — distinct from `require_admin`
    above, which only checks the tenant-scoped `role`. A tenant's own ADMIN
    still can't see other tenants' data; only `is_platform_admin` can.

    `current_user.is_platform_admin` is checked on their own,
    already-tenant-scoped row (fetched by `get_current_user` above) —
    only once that's confirmed does RLS bypass turn on, for the rest of
    this request. The whole point of the admin panel is cross-tenant
    visibility (aggregate stats, every tenant's users), so this is the one
    place bypass is meant to outlive a single query."""
    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissão insuficiente",
        )
    await bypass_rls(session)
    return current_user
