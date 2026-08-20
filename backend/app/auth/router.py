"""Authentication endpoints: register, login, refresh."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_request_settings
from app.auth.schemas import GoogleAuthIn, LoginIn, RefreshIn, RegisterIn, TokenPair
from app.auth.service import (
    EmailAlreadyRegistered,
    authenticate,
    authenticate_google,
    register_user,
)
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

_google_request = google_requests.Request()

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


@router.post(
    "/google",
    response_model=TokenPair,
    dependencies=[Depends(_auth_rate_limit)],
    summary="Autenticar com Google (ID token) e obter tokens",
)
async def login_google(
    data: GoogleAuthIn,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> TokenPair:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login com Google não configurado neste ambiente",
        )
    try:
        claims = google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            data.id_token, _google_request, settings.google_client_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token do Google inválido",
        ) from exc

    email = claims.get("email")
    google_sub = claims.get("sub")
    if not email or not google_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token do Google sem e-mail/sub",
        )
    if claims.get("email_verified") is not True:
        # Google can issue a validly-signed token asserting an email that
        # was never confirmed by its owner (e.g. Workspace-provisioned
        # addresses). Trusting it here would let an attacker link their
        # Google identity to — or create an account under — someone else's
        # email. Never link/create on an unverified email.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail do Google não verificado",
        )

    user = await authenticate_google(
        session, google_sub=google_sub, email=email, full_name=claims.get("name")
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Conta desativada",
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
