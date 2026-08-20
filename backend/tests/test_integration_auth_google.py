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
        lambda *a, **k: {
            "sub": f"sub-{uuid.uuid4().hex}",
            "email": email,
            "email_verified": True,
            "name": "Google User",
        },
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
            lambda *a, **k: {
                "sub": sub,
                "email": email,
                "email_verified": True,
                "name": "Linked User",
            },
        )
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
        assert resp.status_code == 200
        access = resp.json()["access_token"]

        me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
        assert me.json()["id"] == original_user_id  # same account, now linked


async def test_google_login_rejects_unverified_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: an unverified email must never be linked/trusted.

    Google can issue a validly-signed token asserting an email that was
    never confirmed by its owner (e.g. Workspace-provisioned addresses) —
    trusting it would let an attacker link their Google identity to, or
    create an account under, someone else's email.
    """
    monkeypatch.setattr(
        "app.auth.router.google_id_token.verify_oauth2_token",
        lambda *a, **k: {
            "sub": f"sub-{uuid.uuid4().hex}",
            "email": f"unverified-{uuid.uuid4().hex}@example.com",
            "email_verified": False,
            "name": "Not Verified",
        },
    )
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
    assert resp.status_code == 401


async def test_google_login_rejects_missing_email_verified_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absence of the claim must be treated the same as False — fail closed."""
    monkeypatch.setattr(
        "app.auth.router.google_id_token.verify_oauth2_token",
        lambda *a, **k: {"sub": f"sub-{uuid.uuid4().hex}", "email": "no-claim@example.com"},
    )
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
    assert resp.status_code == 401


async def test_google_login_does_not_link_account_with_unverified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attacker asserting a victim's email (unverified) must not hijack their account."""
    victim_email = f"victim-{uuid.uuid4().hex}@example.com"
    app = create_app(_settings_with_google())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        reg = await client.post(
            "/api/v1/auth/register", json={"email": victim_email, "password": "supersecret123"}
        )
        assert reg.status_code == 201

        monkeypatch.setattr(
            "app.auth.router.google_id_token.verify_oauth2_token",
            lambda *a, **k: {
                "sub": f"attacker-sub-{uuid.uuid4().hex}",
                "email": victim_email,
                "email_verified": False,
            },
        )
        resp = await client.post("/api/v1/auth/google", json={"id_token": "whatever"})
        assert resp.status_code == 401

        # The victim's password login must still work, untouched.
        login = await client.post(
            "/api/v1/auth/login", json={"email": victim_email, "password": "supersecret123"}
        )
        assert login.status_code == 200


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
