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


# --- Mobile/web differentiation (Fase 4, ADR-0045) -------------------------
#
# Same server, same REFRESH_COOKIE_ENABLED=True — a client that identifies
# itself as mobile must keep getting the pre-Fase-4 body-based behavior
# (mobile/src/api.ts, SecureStore, ADR-0028), never a cookie. Any other (or
# absent) value on this header must fall back to the safer web/cookie
# behavior — a client can't opt itself *out* of the cookie by omitting the
# header.


async def test_mobile_client_still_gets_refresh_token_in_the_body() -> None:
    # Needs its own app/client (not the module fixture) — nothing here
    # differs from the base fixture except the header sent, but spelling it
    # out keeps this test self-contained and obviously correct on its own.
    settings = Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        public_rate_limit_max=10_000,
        refresh_cookie_enabled=True,
        refresh_cookie_secure=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        email = f"mobile-{uuid.uuid4().hex}@example.com"
        await _register(client, email)

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": _PASSWORD},
            headers={"X-Client-Platform": "mobile"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["refresh_token"]  # present in the body, as mobile expects
        assert "set-cookie" not in resp.headers  # never set on a mobile response

        # The mobile refresh flow (body token in, body token out) keeps working.
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": body["refresh_token"]},
            headers={"X-Client-Platform": "mobile"},
        )
        assert refresh_resp.status_code == 200
        assert refresh_resp.json()["refresh_token"]


async def test_client_platform_header_is_case_insensitive(client: AsyncClient) -> None:
    email = f"mobile-case-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
        headers={"X-Client-Platform": "Mobile"},
    )
    assert resp.json()["refresh_token"]


async def test_unrecognized_client_platform_gets_the_cookie_not_the_body(
    client: AsyncClient,
) -> None:
    email = f"unknown-platform-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
        headers={"X-Client-Platform": "toaster"},
    )
    assert resp.json()["refresh_token"] is None
    assert "stormpulse_refresh=" in resp.headers.get("set-cookie", "")


async def test_body_token_wins_over_cookie_when_both_are_sent(
    client: AsyncClient, settings: Settings
) -> None:
    """Documents and locks in the actual precedence: if a caller sends both
    a body refresh_token and the cookie is also present, the body value is
    what gets used. Neither path grants more than a valid refresh JWT
    already would on its own, so this is safe either way — this test just
    makes sure the choice is deliberate and doesn't silently flip."""
    email = f"both-{uuid.uuid4().hex}@example.com"
    await _register(client, email)
    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert login_resp.status_code == 200
    # `client`'s cookie jar now carries the first user's refresh cookie. A
    # second, independent app/client (own database connection, same
    # Postgres) creates a second user and gets *its* refresh token in the
    # body (as a mobile client would).
    other_email = f"both-other-{uuid.uuid4().hex}@example.com"
    other_app = create_app(settings)
    other_transport = ASGITransport(app=other_app)
    async with (
        other_app.router.lifespan_context(other_app),
        AsyncClient(transport=other_transport, base_url="http://testserver") as other_client,
    ):
        await _register(other_client, other_email)
        other_login = await other_client.post(
            "/api/v1/auth/login",
            json={"email": other_email, "password": _PASSWORD},
            headers={"X-Client-Platform": "mobile"},
        )
        other_refresh_token = other_login.json()["refresh_token"]

    # `client` still carries the FIRST user's cookie. Sending the SECOND
    # user's token in the body must refresh as the second user, not the
    # first — proving the body takes precedence.
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": other_refresh_token})
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.json()["email"] == other_email
