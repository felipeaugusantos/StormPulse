"""Liveness and readiness endpoints.

- ``GET /health`` — liveness: the process is up. No external dependencies.
- ``GET /ready``  — readiness: can we serve traffic? Checks Postgres + Redis.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import __version__
from app.api.deps import get_request_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

CheckState = Literal["ok", "error", "skipped"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, CheckState]


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(request: Request) -> HealthResponse:
    """Return 200 whenever the process is alive."""
    settings = get_request_settings(request)
    return HealthResponse(status="ok", service=settings.app_name, version=__version__)


async def _check_database(engine: AsyncEngine, timeout: float) -> CheckState:
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("readiness: database check failed", extra={"error": str(exc)})
        return "error"


async def _check_redis(redis: object, timeout: float) -> CheckState:
    try:
        async with asyncio.timeout(timeout):
            await redis.ping()  # type: ignore[attr-defined]
        return "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("readiness: redis check failed", extra={"error": str(exc)})
        return "error"


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
async def ready(request: Request, response: Response) -> ReadyResponse:
    """Verify critical dependencies are reachable."""
    settings = get_request_settings(request)
    timeout = settings.readiness_timeout_seconds

    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    redis = getattr(request.app.state, "redis", None)

    db_state = await _check_database(engine, timeout) if engine is not None else "skipped"
    redis_state = await _check_redis(redis, timeout) if redis is not None else "skipped"

    checks: dict[str, CheckState] = {"database": db_state, "redis": redis_state}
    all_ok = all(state == "ok" for state in checks.values())

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadyResponse(status="ready" if all_ok else "not_ready", checks=checks)
