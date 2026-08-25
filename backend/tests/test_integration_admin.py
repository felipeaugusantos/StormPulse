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
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.enums import StormSeverity
from app.lightning.models import LightningStrike
from app.main import create_app
from app.satellite.models import SatelliteImage
from app.storms.models import StormCell
from tests.conftest import register_and_login
from workers.db import session_scope

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


async def _register(client: AsyncClient, email: str) -> str:
    """Registers ``email`` and returns its user id."""
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    resp.raise_for_status()
    return str(resp.json()["id"])


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


async def test_non_admin_gets_403_on_update_and_audit_log(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        f"/api/v1/admin/users/{uuid.uuid4()}",
        json={"is_active": False, "confirm": True},
        headers=headers,
    )
    assert resp.status_code == 403

    resp = await client.get("/api/v1/admin/audit-log", headers=headers)
    assert resp.status_code == 403


async def test_update_missing_confirm_field_is_a_validation_error(client: AsyncClient) -> None:
    """`confirm` has no default (same pattern as `DeleteAccountIn`) — an
    omitted field never reaches the handler at all, FastAPI rejects it at
    the request-validation layer, before any app-level "confirm=false"
    check could run."""
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_id = await _register(client, f"target-{uuid.uuid4().hex}@example.com")

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}", json={"is_active": False}, headers=headers
        )
        assert resp.status_code == 422


async def test_update_with_confirm_false_is_rejected(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_id = await _register(client, f"target-{uuid.uuid4().hex}@example.com")

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}",
            json={"is_active": False, "confirm": False},
            headers=headers,
        )
        assert resp.status_code == 400


async def test_deactivate_user_writes_audit_log_entry(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_email = f"target-{uuid.uuid4().hex}@example.com"
    target_id = await _register(client, target_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}",
            json={"is_active": False, "confirm": True},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        # The deactivated account can no longer log in at all.
        login_attempt = await admin_client.post(
            "/api/v1/auth/login", json={"email": target_email, "password": _PASSWORD}
        )
        assert login_attempt.status_code == 401

        log_resp = await admin_client.get("/api/v1/admin/audit-log", headers=headers)
        assert log_resp.status_code == 200
        entries = log_resp.json()["items"]
        assert entries[0]["action"] == "user.deactivate"
        assert entries[0]["target_email"] == target_email
        assert entries[0]["actor_email"] == admin_email
        assert entries[0]["detail"] == {"is_active": {"from": True, "to": False}}


async def test_role_change_to_admin_writes_audit_log_entry(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_email = f"target-{uuid.uuid4().hex}@example.com"
    target_id = await _register(client, target_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}",
            json={"role": "admin", "confirm": True},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

        log_resp = await admin_client.get("/api/v1/admin/audit-log", headers=headers)
        entries = log_resp.json()["items"]
        assert entries[0]["action"] == "user.role_change"
        assert entries[0]["detail"] == {"role": {"from": "user", "to": "admin"}}


async def test_unsupported_role_is_rejected(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_id = await _register(client, f"target-{uuid.uuid4().hex}@example.com")

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}",
            json={"role": "meteorologist", "confirm": True},
            headers=headers,
        )
        assert resp.status_code == 400


async def test_operator_cannot_deactivate_own_account(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    admin_id = await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{admin_id}",
            json={"is_active": False, "confirm": True},
            headers=headers,
        )
        assert resp.status_code == 400


async def test_update_nonexistent_user_returns_404(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{uuid.uuid4()}",
            json={"is_active": False, "confirm": True},
            headers=headers,
        )
        assert resp.status_code == 404


async def test_update_with_no_fields_returns_400(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    target_id = await _register(client, f"target-{uuid.uuid4().hex}@example.com")

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.put(
            f"/api/v1/admin/users/{target_id}", json={"confirm": True}, headers=headers
        )
        assert resp.status_code == 400


async def test_non_admin_gets_403_on_stats(client: AsyncClient) -> None:
    token = await register_and_login(client)
    resp = await client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_login_stamps_last_login_at(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    target_email = f"target-{uuid.uuid4().hex}@example.com"
    target_id = await _register(client, target_email)
    await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # target_email was only ever registered, never logged in.
        resp = await admin_client.get(
            "/api/v1/admin/users", params={"search": target_email}, headers=headers
        )
        assert resp.json()["items"][0]["last_login_at"] is None

        # Once it logs in, the field is stamped.
        await admin_client.post(
            "/api/v1/auth/login", json={"email": target_email, "password": _PASSWORD}
        )
        resp = await admin_client.get(
            "/api/v1/admin/users", params={"search": target_email}, headers=headers
        )
        assert resp.json()["items"][0]["last_login_at"] is not None
        assert resp.json()["items"][0]["id"] == target_id


async def test_stats_reflects_recent_logins_and_counts(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)
    await _register(client, f"other-{uuid.uuid4().hex}@example.com")

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
        await admin_client.post("/api/v1/locations", json=location_payload, headers=headers)

        resp = await admin_client.get("/api/v1/admin/stats", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_tenants"] >= 2
        assert body["total_users"] >= 2
        # The admin itself just logged in — counted in both windows.
        assert body["active_users_7d"] >= 1
        assert body["active_users_30d"] >= body["active_users_7d"]
        assert body["total_locations"] >= 1


async def test_non_admin_gets_403_on_pipeline_health(client: AsyncClient) -> None:
    token = await register_and_login(client)
    resp = await client.get(
        "/api/v1/admin/pipeline-health", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_pipeline_health_reflects_fresh_and_stale_data(client: AsyncClient) -> None:
    # FASE 34 follow-up: this is the same freshness check that previously
    # had to be done by hand over SSH (curling /public/satellite/image,
    # reading captured_at) — surfaced here instead.
    now = datetime.now(UTC)
    with session_scope() as session:
        for stale in session.scalars(select(SatelliteImage)).all():
            session.delete(stale)
        session.add(
            SatelliteImage(
                captured_at=now,
                bbox_lon_min=-74.0,
                bbox_lat_min=-34.0,
                bbox_lon_max=-34.0,
                bbox_lat_max=6.0,
                band="B13",
                width=10,
                height=8,
                png_data=b"\x89PNG",
                is_mock=False,
                experimental=True,
            )
        )
        # Fresh lightning strike (well within the 300s*2 staleness window).
        session.add(
            LightningStrike(detected_at=now, latitude=-23.5, longitude=-46.6, is_mock=False)
        )
        # Storm cell old enough to be flagged stale (> 2x the 300s interval).
        session.add(
            StormCell(
                detected_at=now - timedelta(hours=1),
                latitude=-23.5,
                longitude=-46.6,
                severity=StormSeverity.MODERATE,
                is_mock=False,
                created_at=now - timedelta(hours=1),
            )
        )

    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.get("/api/v1/admin/pipeline-health", headers=headers)
        assert resp.status_code == 200
        by_name = {row["name"]: row for row in resp.json()}

        assert by_name["satellite"]["stale"] is False
        assert by_name["satellite"]["last_updated_at"] is not None
        assert by_name["lightning"]["stale"] is False
        assert by_name["storms"]["stale"] is True

    with session_scope() as session:
        for stale_image in session.scalars(select(SatelliteImage)).all():
            session.delete(stale_image)
        for stale_strike in session.scalars(select(LightningStrike)).all():
            session.delete(stale_strike)
        for stale_cell in session.scalars(select(StormCell)).all():
            session.delete(stale_cell)


async def test_non_admin_gets_403_on_pipeline_trigger(client: AsyncClient) -> None:
    token = await register_and_login(client)
    resp = await client.post(
        "/api/v1/admin/pipeline-health/trigger",
        json={"name": "satellite"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_pipeline_trigger_rejects_unknown_name(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.post(
            "/api/v1/admin/pipeline-health/trigger",
            json={"name": "not-a-real-pipeline"},
            headers=headers,
        )
        assert resp.status_code == 404


async def test_pipeline_trigger_queues_a_known_pipeline(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    async for admin_client in _promoted_client(admin_email):
        login = await admin_client.post(
            "/api/v1/auth/login", json={"email": admin_email, "password": _PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await admin_client.post(
            "/api/v1/admin/pipeline-health/trigger",
            json={"name": "storms"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"queued": True, "name": "storms"}
