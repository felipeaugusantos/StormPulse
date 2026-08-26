"""Shared pytest fixtures.

Most tests here exercise the application without requiring live Postgres/
Redis (readiness dependency checks are patched where a specific outcome is
needed). Tests marked ``@pytest.mark.integration`` (FASE 14) DO need a real
Postgres+PostGIS and Redis reachable at the configured host/port — the
``pytest_collection_modifyitems`` hook below auto-skips them when those
aren't available, so ``pytest`` still runs clean with no external services
for anyone not using Docker.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # Rate limits are raised here: they're already covered in isolation by
    # test_ratelimit.py against a controlled fake Redis. Integration tests
    # share one real Redis instance across many auth calls in a tight loop,
    # so the default (production-sane) limits would make them flaky.
    return Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        public_rate_limit_max=10_000,
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    # Run the lifespan so app.state is populated (engine/redis clients), and
    # drive the app through an ASGI transport in the same context.
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


def _tcp_reachable(host: str, port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-skip ``@pytest.mark.integration`` tests when Postgres/Redis aren't reachable."""
    real_settings = get_settings()
    available = _tcp_reachable(
        real_settings.postgres_host, real_settings.postgres_port
    ) and _tcp_reachable(real_settings.redis_host, real_settings.redis_port)
    if available:
        return
    skip_marker = pytest.mark.skip(
        reason="Postgres/Redis não disponíveis — testes de integração pulados (FASE 14)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


async def register_and_login(client: AsyncClient, *, password: str = "supersecret123") -> str:
    """Register a user with a unique e-mail and return an access token."""
    email = f"test-{uuid.uuid4().hex}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "accept_terms": True},
    )
    resp.raise_for_status()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    token: str = resp.json()["access_token"]
    return token
