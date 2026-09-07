"""Integration tests for the recommended-actions endpoint (Fase 5,
ADR-0089).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Rows are inserted directly via the sync workers session, same pattern as
``test_integration_risk_digest.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.enums import RiskLevel
from app.recommendations.models import RecommendedAction
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_location(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/locations",
        json={
            "name": "Fazenda (teste recomendações)",
            "kind": "farm",
            "latitude": -21.1775,
            "longitude": -47.8103,
            "radius_km": 10,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return str(resp.json()["id"])


async def test_empty_list_for_a_location_with_no_recommendations(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    resp = await client.get(f"/api/v1/locations/{location_id}/recommended-actions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_returns_a_recommendation_created_by_the_pipeline(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            RecommendedAction(
                tenant_id=me["tenant_id"],
                location_id=location_id,
                rule_key="frost_severe_irrigation",
                title="Geada severa prevista",
                message="Considere irrigação por aspersão ou cobertura das plantas.",
                level=RiskLevel.RED,
                alert_id=None,
                snapshot_json=json.dumps({"frost_temperature_c": 1.0}),
            )
        )

    resp = await client.get(f"/api/v1/locations/{location_id}/recommended-actions", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["rule_key"] == "frost_severe_irrigation"
    assert body[0]["level"] == "red"
    assert body[0]["alert_id"] is None


async def test_recommendations_older_than_three_days_are_not_returned(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            RecommendedAction(
                tenant_id=me["tenant_id"],
                location_id=location_id,
                rule_key="frost_severe_irrigation",
                title="Geada severa prevista (antiga)",
                message="Fora da janela de exibição.",
                level=RiskLevel.RED,
                alert_id=None,
                snapshot_json="{}",
                created_at=datetime.now(UTC) - timedelta(days=10),
            )
        )

    resp = await client.get(f"/api/v1/locations/{location_id}/recommended-actions", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_another_users_location_is_404(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    location_id = await _create_location(client, owner_headers)

    other_headers = await _auth_headers(client)
    resp = await client.get(
        f"/api/v1/locations/{location_id}/recommended-actions", headers=other_headers
    )
    assert resp.status_code == 404
