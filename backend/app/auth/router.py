"""Authentication endpoints: register, login, refresh."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.core.config import Settings
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


async def _auth_rate_limit(request: Request) -> None:
    """Built from *this request's* app settings, not a module-level
    singleton — a `RateLimiter` built once at import time (the previous
    approach) would freeze whichever `Settings` happened to be current the
    first time this module was imported, ignoring the actual app instance's
    config in any process running more than one (e.g. tests exercising two
    different configs — see ADR-0030/`test_multi_app_settings_isolation`).
    Cheap to rebuild per-request: `RateLimiter` holds no state of its own,
    it's just a thin wrapper around a Redis key."""
    settings = get_request_settings(request)
    limiter = RateLimiter(
        max_requests=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
        scope="auth",
    )
    await limiter(request)


async def _touch_last_login(session: AsyncSession, user: User) -> None:
    """Stamps `last_login_at` on a real sign-in (FASE 28 Fase 3, ADR-0051)
    — never on a token refresh, which happens automatically in the
    background and isn't a deliberate login. The only reader is the
    platform-admin "active users" metric."""
    user.last_login_at = datetime.now(UTC)
    await session.commit()


def _issue_tokens(user: User, settings: Settings) -> TokenPair:
    subject = str(user.id)
    claims = {"role": user.role.value, "tenant_id": str(user.tenant_id)}
    return TokenPair(
        access_token=create_access_token(subject, settings, extra_claims=claims),
        refresh_token=create_refresh_token(subject, settings),
    )


def _is_mobile_client(request: Request) -> bool:
    """The mobile app explicitly identifies itself (`mobile/src/api.ts`
    sends this on every auth call) so the backend can keep serving it the
    body-based refresh token flow (SecureStore) even with the web cookie
    flow (Fase 4) on by default — an unrecognized/absent header is always
    treated as "web", never the other way around, so a client can't opt
    itself *out* of the safer cookie behavior by omitting a header."""
    return request.headers.get("x-client-platform", "").strip().lower() == "mobile"


def _apply_token_response(
    tokens: TokenPair, request: Request, response: Response, settings: Settings
) -> TokenPair:
    """Web (default): when the refresh-token cookie is enabled (ADR-0029,
    completed in the hardening Fase 4 — ADR-0045), sets it as an HttpOnly
    cookie and strips it from the JSON body, so it's never readable from
    JS. Mobile (`X-Client-Platform: mobile`): always returns `tokens`
    untouched, regardless of the cookie setting — it keeps using the
    body-based refresh token, stored in `expo-secure-store` (ADR-0028),
    never a cookie. Never both at once for the same request: a client
    identifying as mobile never gets a cookie set on it."""
    if _is_mobile_client(request) or not settings.refresh_cookie_enabled:
        return tokens
    assert tokens.refresh_token is not None  # always set here, before stripping
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )
    return tokens.model_copy(update={"refresh_token": None})


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    # delete_cookie is a no-op (still a harmless Set-Cookie header) if the
    # browser never had this cookie — logout stays idempotent either way.
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
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
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> TokenPair:
    user = await authenticate(session, data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
        )
    await _touch_last_login(session, user)
    return _apply_token_response(_issue_tokens(user, settings), request, response, settings)


@router.post(
    "/google",
    response_model=TokenPair,
    dependencies=[Depends(_auth_rate_limit)],
    summary="Autenticar com Google (ID token) e obter tokens",
)
async def login_google(
    data: GoogleAuthIn,
    request: Request,
    response: Response,
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
    await _touch_last_login(session, user)
    return _apply_token_response(_issue_tokens(user, settings), request, response, settings)


@router.post("/refresh", response_model=TokenPair, summary="Renovar tokens")
async def refresh(
    data: RefreshIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> TokenPair:
    # Accept the refresh token from either the body (default today) or the
    # cookie (ADR-0029, opt-in) — whichever the client actually sent.
    refresh_token = data.refresh_token or (
        request.cookies.get(settings.refresh_cookie_name)
        if settings.refresh_cookie_enabled
        else None
    )
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ausente",
        )
    try:
        payload = decode_token(refresh_token, settings, expected_type="refresh")
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
    return _apply_token_response(_issue_tokens(user, settings), request, response, settings)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Encerrar sessão (limpa o cookie de refresh, se configurado)",
)
async def logout(
    response: Response,
    settings: Settings = Depends(get_request_settings),
) -> None:
    # Stateless by design: the access token simply expires (15min) and the
    # client is expected to discard both tokens client-side too. This only
    # has cookie state to clear when ADR-0029's cookie is enabled — with it
    # off (default), this is a no-op 204, which is still the correct
    # contract for a client that always calls it on sign-out.
    _clear_refresh_cookie(response, settings)
