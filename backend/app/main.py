"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import public_v1_router, root_router, v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.metrics import configure_metrics
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter
from app.core.rls import verify_rls_safety
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.tracing import configure_tracing
from app.db.redis import create_redis
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


async def _bootstrap_platform_admin(app: FastAPI, settings: Settings) -> None:
    """Promote PLATFORM_ADMIN_EMAIL to a cross-tenant operator (FASE 28,
    ADR-0048), if that account already exists. Idempotent — safe to run on
    every startup; a no-op once the flag is already set, and a no-op
    entirely if the account hasn't registered yet (never creates one)."""
    if not settings.platform_admin_email:
        return
    from sqlalchemy import select

    from app.core.crypto import blind_index
    from app.core.rls import bypass_rls
    from app.users.models import User

    session_factory = app.state.session_factory
    async with session_factory() as session:
        # Startup, outside any request — no tenant is known yet, and this
        # lookup is inherently cross-tenant (by email, same as login). RLS
        # (migration 0b7b9a5dbd11) would otherwise fail it closed.
        await bypass_rls(session)
        result = await session.execute(
            select(User).where(
                User.email_index == blind_index(settings.platform_admin_email.lower())
            )
        )
        user = result.scalar_one_or_none()
        if user is not None and not user.is_platform_admin:
            user.is_platform_admin = True
            await session.commit()
            logger.info("promoted platform admin", extra={"email": user.email})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and dispose shared resources (DB engine, Redis client)."""
    settings: Settings = app.state.settings
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
    # Fails startup outright in production (never serves a request with a
    # broken RLS setup); everywhere else just warns — see
    # verify_rls_safety's own docstring for why local/CI get the pass.
    await verify_rls_safety(app.state.engine, settings)
    # Gated only by PLATFORM_ADMIN_EMAIL being set (see the function's own
    # early return) — not by environment, so integration tests can exercise
    # the real startup path instead of a parallel test-only code path.
    await _bootstrap_platform_admin(app, settings)
    logger.info("application startup complete", extra={"environment": settings.environment})
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()
        logger.info("application shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "StormPulse — plataforma de monitoramento meteorológico acionável "
            "(Waze de tempestades). API da FASE 1 (fundação)."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(root_router)
    default_rate_limit = RateLimiter(
        max_requests=settings.default_rate_limit_max,
        window_seconds=settings.default_rate_limit_window_seconds,
        scope="default",
    )
    app.include_router(
        v1_router,
        prefix=settings.api_v1_prefix,
        dependencies=[Depends(default_rate_limit)],
    )
    public_rate_limit = RateLimiter(
        max_requests=settings.public_rate_limit_max,
        window_seconds=settings.public_rate_limit_window_seconds,
        scope="public",
    )
    app.include_router(
        public_v1_router,
        prefix=settings.api_v1_prefix,
        dependencies=[Depends(public_rate_limit)],
    )

    if settings.otel_enabled and settings.environment != "test":
        configure_tracing(app, settings)
        configure_metrics(settings)

    return app


app = create_app()
