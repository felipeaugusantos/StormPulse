"""Shared pytest fixtures.

Tests here exercise the application without requiring live Postgres/Redis.
An ``httpx.ASGITransport`` drives the app (including lifespan), and readiness
dependency checks are patched where a specific outcome is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", log_json=False, log_level="WARNING")


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
