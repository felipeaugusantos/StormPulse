"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import root_router, v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.tracing import configure_tracing
from app.db.redis import create_redis
from app.db.session import create_engine, create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and dispose shared resources (DB engine, Redis client)."""
    settings: Settings = app.state.settings
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings)
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

    if settings.otel_enabled and settings.environment != "test":
        configure_tracing(app, settings)

    return app


app = create_app()
