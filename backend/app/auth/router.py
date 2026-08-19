"""Authentication endpoints: register, login, refresh."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.auth.schemas import LoginIn, RefreshIn, RegisterIn, TokenPair
from app.auth.service import EmailAlreadyRegistered, authenticate, register_user
from app.core.config import Settings, get_settings
from app.core.ratelimit import RateLimiter
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.users.models import User
from app.users.schemas import UserOut

router = APIRouter(tags=["auth"])

_settings = get_settings()
_auth_rate_limit = RateLimiter(
    max_requests=_settings.auth_rate_limit_max,
    window_seconds=_settings.auth_rate_limit_window_seconds,
    scope="auth",
)


def _issue_tokens(user: User, settings: Settings) -> TokenPair:
    subject = str(user.id)
    claims = {"role": user.role.value, "tenant_id": str(user.tenant_id)}
    return TokenPair(
        access_token=create_access_token(subject, settings, extra_claims=claims),
        refresh_token=create_refresh_token(subject, settings),
    )


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_auth_rate_limit)],
    summary="Registrar novo usuário",
)
async def register(
    data: RegisterIn,
    session: AsyncSession = Depends(get_db),
) -> User:
    try:
        return await register_user(session, data)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-mail já cadastrado",
        ) from exc


@router.post(
    "/login",
    response_model=TokenPair,
    dependencies=[Depends(_auth_rate_limit)],
    summary="Autenticar e obter tokens",
)
async def login(
    data: LoginIn,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    user = await authenticate(session, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
        )
    return _issue_tokens(user, settings)


@router.post("/refresh", response_model=TokenPair, summary="Renovar tokens")
async def refresh(
    data: RefreshIn,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenPair:
    try:
        payload = decode_token(data.refresh_token, settings, expected_type="refresh")
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido",
        ) from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário inválido",
        )
    return _issue_tokens(user, settings)
