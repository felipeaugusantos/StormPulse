"""Tests for liveness/readiness endpoints and request-context middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import __version__


async def test_health_is_alive(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "StormPulse"
    assert body["version"] == __version__


async def test_health_sets_request_id_header(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.headers.get("X-Request-ID")


async def test_health_propagates_correlation_id(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Correlation-ID": "corr-123"})
    assert resp.headers.get("X-Correlation-ID") == "corr-123"


async def test_ready_when_dependencies_ok(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok(*_args: object, **_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("app.api.health._check_database", _ok)
    monkeypatch.setattr("app.api.health._check_redis", _ok)

    resp = await client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


async def test_ready_returns_503_when_database_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _db_error(*_args: object, **_kwargs: object) -> str:
        return "error"

    async def _redis_ok(*_args: object, **_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("app.api.health._check_database", _db_error)
    monkeypatch.setattr("app.api.health._check_redis", _redis_ok)

    resp = await client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "error"


async def test_openapi_is_available(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "StormPulse"
