"""Integration tests for the cross-tenant platform-admin panel (FASE 28,
ADR-0048).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
The PLATFORM_ADMIN_EMAIL bootstrap only promotes an *already-registered*
account, and only runs at app startup — so tests that need a promoted user
register normally against the default ``client`` fixture first, then spin up
a second, independent app (``create_app``, own lifespan) with
``platform_admin_email`` set to that same address, mirroring exactly the
real-world sequence (register, then restart the API with the env var set).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

_PASSWORD = "supersecret123"


async def _promoted_client(email: str) -> AsyncIterator[AsyncClient]:
    """A fresh app/client whose startup bootstrap promotes ``email`` to
    platform admin (it must already be registered against the shared DB)."""
    settings = Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        public_rate_limit_max=10_000,
        platform_admin_email=email,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


async def test_non_admin_gets_403_on_user_list(client: AsyncClient) -> None:
    token = await register_and_login(client)
    resp = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_non_admin_gets_403_on_tenant_list(client: AsyncClient) -> None:
    token = await register_and_login(client)
    resp = await client.get("/api/v1/admin/tenants", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_bootstrap_promotes_an_already_registered_email(client: AsyncClient) -> None:
    email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 201

    async for admin_client in _promoted_client(email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
        )
        token = login.json()["access_token"]

        me = await admin_client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me.json()["is_platform_admin"] is True


async def test_bootstrap_never_promotes_an_unregistered_email(client: AsyncClient) -> None:
    """The email in PLATFORM_ADMIN_EMAIL simply hasn't signed up yet — the
    bootstrap must not create an account, and must not error either."""
    email = f"never-registered-{uuid.uuid4().hex}@example.com"

    async for admin_client in _promoted_client(email):
        resp = await admin_client.post(
            "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
        )
        assert resp.status_code == 401  # no such account was ever created


async def test_platform_admin_sees_users_across_tenants(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": admin_email, "password": _PASSWORD})
    # A second, unrelated tenant/user that the platform admin should still see.
    other_email = f"other-tenant-{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": other_email, "password": _PASSWORD})

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await admin_client.get("/api/v1/admin/users", params={"limit": 200}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        emails = {u["email"] for u in body["items"]}
        assert admin_email in emails
        assert other_email in emails
        # Each user carries its own tenant's name, not the admin's.
        by_email = {u["email"]: u for u in body["items"]}
        assert by_email[admin_email]["tenant_id"] != by_email[other_email]["tenant_id"]


async def test_platform_admin_users_search_filters_by_email(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": admin_email, "password": _PASSWORD})
    needle = uuid.uuid4().hex
    target_email = f"needle-{needle}@example.com"
    await client.post("/api/v1/auth/register", json={"email": target_email, "password": _PASSWORD})

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = await admin_client.get(
            "/api/v1/admin/users", params={"search": needle}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [u["email"] for u in body["items"]] == [target_email]
        assert body["total"] == 1


async def test_platform_admin_sees_tenant_counts(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": admin_email, "password": _PASSWORD})

    location_payload = {
        "name": "Fazenda",
        "kind": "farm",
        "latitude": -23.5,
        "longitude": -46.6,
        "radius_km": 20,
    }

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        create = await admin_client.post(
            "/api/v1/locations", json=location_payload, headers=headers
        )
        assert create.status_code == 201

        resp = await admin_client.get("/api/v1/admin/tenants", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        me_tenant_id = (await admin_client.get("/api/v1/users/me", headers=headers)).json()[
            "tenant_id"
        ]
        by_id = {t["id"]: t for t in body["items"]}
        assert by_id[me_tenant_id]["user_count"] >= 1
        assert by_id[me_tenant_id]["location_count"] == 1
