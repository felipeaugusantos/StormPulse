"""FastAPI dependencies: DB session, current user and RBAC guards."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.enums import UserRole
from app.core.security import TokenError, decode_token
from app.users.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an async DB session from the app's session factory."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the authenticated user from a Bearer access token."""
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

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
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
