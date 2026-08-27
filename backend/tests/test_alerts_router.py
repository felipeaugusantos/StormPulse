"""Tests for GET /alerts' time-window filtering.

The alerts feed is "what needs attention now", not the permanent audit
log (every Alert row stays in the database regardless of this filter) —
reported live in production (2026-08-27): an already-resolved satellite
watch alert from the day before stayed in the last-50 feed, reading as
still relevant. Needs real Postgres — auto-skipped otherwise (see
conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.alerts.models import Alert
from app.core.enums import AlertEventType, RiskLevel
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


async def _insert_alert(
    client: AsyncClient, headers: dict[str, str], *, created_at: datetime
) -> None:
    me = (await client.get("/api/v1/users/me", headers=headers)).json()
    location = (
        await client.post(
            "/api/v1/locations",
            json={"name": "Fazenda", "latitude": -21.18, "longitude": -47.81},
            headers=headers,
        )
    ).json()
    unique = uuid.uuid4().hex
    with session_scope() as session:
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=location["id"],
                event_type=AlertEventType.SATELLITE_WATCH_DISSIPATED,
                level=RiskLevel.YELLOW,
                title="Observação via satélite dissipada",
                message="Teste",
                dedup_key=f"test-alerts-window:{unique}",
                created_at=created_at,
            )
        )


async def test_alerts_feed_excludes_events_older_than_the_default_window(
    client: AsyncClient,
) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC)

    await _insert_alert(client, headers, created_at=now - timedelta(hours=2))
    await _insert_alert(client, headers, created_at=now - timedelta(hours=48))

    resp = await client.get("/api/v1/alerts", headers=headers)
    assert resp.status_code == 200
    ages_hours = [
        (now - datetime.fromisoformat(a["created_at"])).total_seconds() / 3600 for a in resp.json()
    ]
    assert all(age < 24 for age in ages_hours)
    assert len(resp.json()) == 1


async def test_alerts_feed_window_hours_is_overridable(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC)

    await _insert_alert(client, headers, created_at=now - timedelta(hours=48))

    resp = await client.get("/api/v1/alerts", params={"window_hours": 72}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
