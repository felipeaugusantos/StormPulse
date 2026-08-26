"""Integration tests for the meteorological validation/backtesting endpoints
(ADR-0036/0058) — real Postgres, real HTTP, never a mocked DB.

Fixtures build tenant/user/location/alert/storm_risk directly in a sync
session (same pattern as ``test_notification_pipeline.py``), then a
promoted platform-admin client records verifications and reads metrics
through the real API, exactly as an operator would.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.alerts.verification_models import AlertVerification
from app.core.config import Settings
from app.core.crypto import blind_index
from app.core.enums import AlertEventType, RiskLevel
from app.locations.models import Location
from app.main import create_app
from app.storms.models import StormRisk
from app.tenants.models import Tenant
from app.users.models import User
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration

_PASSWORD = "supersecret123"


async def _promoted_client(email: str) -> AsyncIterator[AsyncClient]:
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


async def _register(client: AsyncClient, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"accept_terms": True, "email": email, "password": _PASSWORD}
    )
    resp.raise_for_status()


async def _admin_headers(client: AsyncClient, email: str) -> dict[str, str]:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    login.raise_for_status()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_tenant_user_location(session: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"val-{unique}@example.com"
    user = User(
        tenant_id=tenant.id,
        email=email,
        email_index=blind_index(email),
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(user)
    session.flush()
    location = Location(
        tenant_id=tenant.id,
        user_id=user.id,
        name="Fazenda (teste)",
        kind="farm",
        latitude=-21.1775,
        longitude=-47.8103,
        radius_km=10,
        is_active=True,
    )
    session.add(location)
    session.flush()
    return tenant.id, user.id, location.id


def _make_alert(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    location_id: uuid.UUID,
    event_type: AlertEventType = AlertEventType.STORM_APPROACHING,
    storm_risk_id: uuid.UUID | None = None,
) -> Alert:
    unique = uuid.uuid4().hex
    alert = Alert(
        tenant_id=tenant_id,
        user_id=user_id,
        location_id=location_id,
        storm_risk_id=storm_risk_id,
        event_type=event_type,
        level=RiskLevel.RED,
        title="Tempestade se aproximando",
        message="Teste",
        dedup_key=f"test-validation:{unique}",
    )
    session.add(alert)
    session.flush()
    return alert


def _clear_alert_verifications(session: Session) -> None:
    """`/admin/validation/metrics` aggregates globally, not per-tenant — a
    fresh tenant alone doesn't isolate a test from other tests' leftover
    rows in this shared Postgres (same real bug class as
    `test_pipeline_health_reflects_fresh_and_stale_data` in
    test_integration_admin.py: a full-suite run left rows behind that made
    an exact-count assertion flaky when other tests ran first)."""
    for row in session.scalars(select(AlertVerification)).all():
        session.delete(row)


def _make_storm_risk(
    session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, eta_minutes: int
) -> StormRisk:
    risk = StormRisk(
        tenant_id=tenant_id,
        location_id=location_id,
        severity=RiskLevel.RED,
        eta_minutes=eta_minutes,
        computed_at=datetime.now(UTC) - timedelta(minutes=5),
        is_mock=True,
        experimental=True,
    )
    session.add(risk)
    session.flush()
    return risk


async def test_non_admin_gets_403_on_verification_endpoints(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    with session_scope() as session:
        tenant_id, user_id, location_id = _make_tenant_user_location(session)
        alert = _make_alert(session, tenant_id=tenant_id, user_id=user_id, location_id=location_id)
        alert_id = alert.id

    resp = await client.put(
        f"/api/v1/admin/alerts/{alert_id}/verification", json={"confirmed": True}, headers=headers
    )
    assert resp.status_code == 403

    resp = await client.get("/api/v1/admin/validation/metrics", headers=headers)
    assert resp.status_code == 403


async def test_verification_upsert_and_404_for_unknown_alert(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    with session_scope() as session:
        tenant_id, user_id, location_id = _make_tenant_user_location(session)
        alert = _make_alert(session, tenant_id=tenant_id, user_id=user_id, location_id=location_id)
        alert_id = alert.id

    async for admin_client in _promoted_client(admin_email):
        headers = await _admin_headers(admin_client, admin_email)

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{uuid.uuid4()}/verification",
            json={"confirmed": True},
            headers=headers,
        )
        assert resp.status_code == 404

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{alert_id}/verification",
            json={"confirmed": False, "notes": "Não choveu no local"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["alert_id"] == str(alert_id)
        assert body["confirmed"] is False
        assert body["notes"] == "Não choveu no local"
        first_id = body["id"]

        # Same alert again — upsert, not a second row.
        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{alert_id}/verification",
            json={"confirmed": True, "notes": "Correção: choveu sim"},
            headers=headers,
        )
        assert resp.status_code == 200
        body2 = resp.json()
        assert body2["id"] == first_id
        assert body2["confirmed"] is True
        assert body2["notes"] == "Correção: choveu sim"


async def test_validation_metrics_computed_from_real_verifications(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    with session_scope() as session:
        _clear_alert_verifications(session)
        tenant_id, user_id, location_id = _make_tenant_user_location(session)
        risk = _make_storm_risk(
            session, tenant_id=tenant_id, location_id=location_id, eta_minutes=30
        )
        # 2 confirmed-true STORM_APPROACHING alerts (one with a resolved ETA
        # sample), 1 confirmed-false — confirmation_rate must be 2/3, never
        # a fabricated/rounded number.
        confirmed_true_1 = _make_alert(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            location_id=location_id,
            storm_risk_id=risk.id,
        )
        confirmed_true_2 = _make_alert(
            session, tenant_id=tenant_id, user_id=user_id, location_id=location_id
        )
        confirmed_false = _make_alert(
            session, tenant_id=tenant_id, user_id=user_id, location_id=location_id
        )
        # An unresolved verification (confirmed=None) must be excluded from
        # every metric — it isn't ground truth yet.
        unresolved = _make_alert(
            session, tenant_id=tenant_id, user_id=user_id, location_id=location_id
        )
        ids = {
            "true_1": confirmed_true_1.id,
            "true_2": confirmed_true_2.id,
            "false": confirmed_false.id,
            "unresolved": unresolved.id,
        }

    actual_arrival = risk.computed_at + timedelta(minutes=35)  # 5 min later than predicted

    async for admin_client in _promoted_client(admin_email):
        headers = await _admin_headers(admin_client, admin_email)

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{ids['true_1']}/verification",
            json={"confirmed": True, "actual_arrival_at": actual_arrival.isoformat()},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{ids['true_2']}/verification",
            json={"confirmed": True},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{ids['false']}/verification",
            json={"confirmed": False},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await admin_client.put(
            f"/api/v1/admin/alerts/{ids['unresolved']}/verification",
            json={"confirmed": None},
            headers=headers,
        )
        assert resp.status_code == 200

        resp = await admin_client.get("/api/v1/admin/validation/metrics", headers=headers)
        assert resp.status_code == 200
        metrics = resp.json()

        assert metrics["sample_size"] == 3
        assert metrics["confirmed_count"] == 2
        assert metrics["confirmation_rate"] == pytest.approx(2 / 3)
        assert metrics["min_sample_size"] == 30
        assert metrics["reliable"] is False

        by_type = metrics["by_event_type"]["storm_approaching"]
        assert by_type["sample_size"] == 3
        assert by_type["confirmed_count"] == 2

        assert metrics["eta_sample_size"] == 1
        assert metrics["mean_absolute_eta_error_minutes"] == pytest.approx(5.0)


async def test_validation_metrics_never_reports_recall(client: AsyncClient) -> None:
    """Every ground-truth row here comes from an *issued* alert — there is
    no source of false negatives (a real event nobody alerted on), so
    `ValidationMetricsOut` must never expose a `recall` field that would
    silently read as a fabricated-looking 1.0."""
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    with session_scope() as session:
        _clear_alert_verifications(session)
        tenant_id, user_id, location_id = _make_tenant_user_location(session)
        alert = _make_alert(session, tenant_id=tenant_id, user_id=user_id, location_id=location_id)
        alert_id = alert.id

    async for admin_client in _promoted_client(admin_email):
        headers = await _admin_headers(admin_client, admin_email)
        await admin_client.put(
            f"/api/v1/admin/alerts/{alert_id}/verification",
            json={"confirmed": True},
            headers=headers,
        )
        resp = await admin_client.get("/api/v1/admin/validation/metrics", headers=headers)
        assert "recall" not in resp.json()
        assert "recall" not in resp.json()["by_event_type"]["storm_approaching"]


async def test_reliable_flag_flips_at_min_sample_size(client: AsyncClient) -> None:
    admin_email = f"platform-admin-{uuid.uuid4().hex}@example.com"
    await _register(client, admin_email)

    min_sample_size = 30
    with session_scope() as session:
        _clear_alert_verifications(session)
        tenant_id, user_id, location_id = _make_tenant_user_location(session)
        alert_ids = [
            _make_alert(session, tenant_id=tenant_id, user_id=user_id, location_id=location_id).id
            for _ in range(min_sample_size)
        ]

    async for admin_client in _promoted_client(admin_email):
        headers = await _admin_headers(admin_client, admin_email)
        for alert_id in alert_ids:
            resp = await admin_client.put(
                f"/api/v1/admin/alerts/{alert_id}/verification",
                json={"confirmed": True},
                headers=headers,
            )
            assert resp.status_code == 200

        resp = await admin_client.get("/api/v1/admin/validation/metrics", headers=headers)
        metrics = resp.json()
        assert metrics["sample_size"] >= min_sample_size
        assert metrics["reliable"] is True
