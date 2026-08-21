"""Integration tests for the opt-in refresh-token cookie (ADR-0029).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Overrides the module-scoped ``settings``/``client`` fixtures to turn the
cookie on — every other integration test file keeps it off (default),
proving both modes coexist correctly.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration

_PASSWORD = "supersecret123"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        public_rate_limit_max=10_000,
        refresh_cookie_enabled=True,
        # Secure cookies are never sent back by httpx's test transport over
        # plain http://testserver — disabled here purely so assertions on
        # the cookie jar work; REFRESH_COOKIE_SECURE itself is still
        # exercised directly against the Settings validator in
        # test_config.py-style unit tests (production forbids it off).
        refresh_cookie_secure=False,
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


async def _register(client: AsyncClient, email: str) -> None:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 201


async def test_login_sets_httponly_cookie_and_omits_refresh_token_from_body(
    client: AsyncClient,
) -> None:
    email = f"cookie-{uuid.uuid4().hex}@example.com"
    await _register(client, email)

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"] is None  # never in the JS-readable body

    cookie_header = resp.headers.get("set-cookie", "")
    assert "stormpulse_refresh=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Path=/api/v1/auth" in cookie_header
    assert "SameSite=lax" in cookie_header.lower() or "samesite=lax" in cookie_header.lower()


async def test_refresh_accepts_the_cookie_without_a_body_token(client: AsyncClient) -> None:
    email = f"cookie-refresh-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert login_resp.status_code == 200
    # httpx's AsyncClient keeps the cookie jar automatically across calls on
    # the same client — this mirrors a real browser sending it back.
    refresh_resp = await client.post("/api/v1/auth/refresh", json={})
    assert refresh_resp.status_code == 200
    refreshed = refresh_resp.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"] is None


async def test_refresh_without_body_or_cookie_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Refresh token ausente"


async def test_logout_clears_the_cookie(client: AsyncClient) -> None:
    email = f"cookie-logout-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    cookie_header = resp.headers.get("set-cookie", "")
    assert "stormpulse_refresh=" in cookie_header
    # An expired/zeroed Max-Age tells the browser to delete it immediately.
    assert "Max-Age=0" in cookie_header or "max-age=0" in cookie_header.lower()

    # The cleared cookie can no longer refresh a session.
    refresh_resp = await client.post("/api/v1/auth/refresh", json={})
    assert refresh_resp.status_code == 401


async def test_cookie_refreshed_access_token_authenticates_users_me(client: AsyncClient) -> None:
    """End-to-end: the access token obtained via a cookie-driven /refresh
    must be a real, valid token — not just present in the response."""
    email = f"cookie-e2e-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})

    refresh_resp = await client.post("/api/v1/auth/refresh", json={})
    new_access = refresh_resp.json()["access_token"]

    me_resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_access}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email
