"""Integration tests for POST /auth/google (FASE 15).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
conftest.py). Google's own token verification is mocked (no real network
call to Google) — only our account creation/linking logic is under test.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def _settings_with_google() -> Settings:
    return Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        google_client_id="test-client-id.apps.googleusercontent.com",
    )


async def test_google_login_creates_a_new_account(monkeypatch: pytest.MonkeyPatch) -> None:
    email = f"google-{uuid.uuid4().hex}@example.com"
    monkeypatch.setattr(
        "app.auth.router.google_id_token.verify_oauth2_token",
        lambda *a, **k: {"sub": f"sub-{uuid.uuid4().hex}", "email": email, "name": "Google User"},
    )
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
        assert resp.status_code == 200
        access = resp.json()["access_token"]

        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200
        assert me.json()["email"] == email


async def test_google_login_links_existing_password_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"linked-{uuid.uuid4().hex}@example.com"
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        reg = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "supersecret123"}
        )
        assert reg.status_code == 201
        original_user_id = reg.json()["id"]

        sub = f"sub-{uuid.uuid4().hex}"
        monkeypatch.setattr(
            "app.auth.router.google_id_token.verify_oauth2_token",
            lambda *a, **k: {"sub": sub, "email": email, "name": "Linked User"},
        )
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
        assert resp.status_code == 200
        access = resp.json()["access_token"]

        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
        assert me.json()["id"] == original_user_id  # same account, now linked


async def test_google_login_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("Token used too late")

    monkeypatch.setattr("app.auth.router.google_id_token.verify_oauth2_token", _raise)
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.post("/api/v1/auth/google", json={"id_token": "bad"})
    assert resp.status_code == 401


async def test_google_login_without_client_id_returns_503(client: AsyncClient) -> None:
    # The shared `client` fixture's Settings has no google_client_id set.
    resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
    assert resp.status_code == 503
