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
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.enums import AlertEventType, RiskLevel
from app.satellite.models import ConvectiveWatch
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


async def _insert_alert(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    created_at: datetime,
    event_type: AlertEventType = AlertEventType.DRY_SPELL_WARNING,
    convective_watch_id: str | None = None,
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
                convective_watch_id=convective_watch_id,
                event_type=event_type,
                level=RiskLevel.YELLOW,
                title="Alerta de teste",
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


def _make_convective_watch(session: Session) -> str:
    watch = ConvectiveWatch(
        first_detected_at=datetime.now(UTC),
        detected_at=datetime.now(UTC),
        latitude=-21.18,
        longitude=-47.81,
        min_brightness_temp_k=223.0,
        is_active=False,
    )
    session.add(watch)
    session.flush()
    return str(watch.id)


async def test_satellite_detected_alert_is_hidden_once_its_watch_dissipates(
    client: AsyncClient,
) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC)

    with session_scope() as session:
        watch_id = _make_convective_watch(session)

    # Both well within the general 24h window — only the dissipation rule
    # should hide the detected alert.
    await _insert_alert(
        client,
        headers,
        created_at=now - timedelta(hours=16),
        event_type=AlertEventType.SATELLITE_WATCH_DETECTED,
        convective_watch_id=watch_id,
    )
    await _insert_alert(
        client,
        headers,
        created_at=now - timedelta(hours=1),
        event_type=AlertEventType.SATELLITE_WATCH_DISSIPATED,
        convective_watch_id=watch_id,
    )

    resp = await client.get("/api/v1/alerts", headers=headers)
    assert resp.status_code == 200
    event_types = [a["event_type"] for a in resp.json()]
    assert AlertEventType.SATELLITE_WATCH_DETECTED.value not in event_types
    assert AlertEventType.SATELLITE_WATCH_DISSIPATED.value in event_types


async def test_satellite_detected_alert_still_shows_while_its_watch_is_active(
    client: AsyncClient,
) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC)

    with session_scope() as session:
        watch_id = _make_convective_watch(session)

    await _insert_alert(
        client,
        headers,
        created_at=now - timedelta(hours=1),
        event_type=AlertEventType.SATELLITE_WATCH_DETECTED,
        convective_watch_id=watch_id,
    )

    resp = await client.get("/api/v1/alerts", headers=headers)
    assert resp.status_code == 200
    event_types = [a["event_type"] for a in resp.json()]
    assert AlertEventType.SATELLITE_WATCH_DETECTED.value in event_types


async def test_satellite_dissipated_alert_hidden_after_its_own_short_window(
    client: AsyncClient,
) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(UTC)

    with session_scope() as session:
        watch_id = _make_convective_watch(session)

    # 12h old — still within the general 24h window, but past the
    # satellite-dissipated-specific 3h window.
    await _insert_alert(
        client,
        headers,
        created_at=now - timedelta(hours=12),
        event_type=AlertEventType.SATELLITE_WATCH_DISSIPATED,
        convective_watch_id=watch_id,
    )

    resp = await client.get("/api/v1/alerts", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []
