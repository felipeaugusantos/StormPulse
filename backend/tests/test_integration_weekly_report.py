"""Integration tests for the talhão weekly-report endpoint (FASE 32).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Rainfall comes from a live weather-provider call (same as
``/agro/rainfall`` elsewhere in this suite) — alerts/NDVI are inserted
directly via the sync workers session, same pattern as
``test_integration_ndvi.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.alerts.models import Alert
from app.core.enums import AlertEventType, RiskLevel
from app.ndvi.models import NdviReading
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration

_BOUNDARY = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [[[-47.81, -21.18], [-47.80, -21.18], [-47.80, -21.17], [-47.81, -21.18]]],
    }
)


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_farm_and_talhao(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
    farm = (
        await client.post(
            "/api/v1/locations",
            json={
                "name": "Fazenda",
                "kind": "farm",
                "latitude": -21.18,
                "longitude": -47.81,
                "radius_km": 10,
            },
            headers=headers,
        )
    ).json()
    talhao = (
        await client.post(
            "/api/v1/locations",
            json={
                "name": "Talhão",
                "latitude": -21.18,
                "longitude": -47.81,
                "parent_location_id": farm["id"],
                "crop": "soja",
                "boundary_geojson": _BOUNDARY,
            },
            headers=headers,
        )
    ).json()
    return farm["id"], talhao["id"]


async def test_weekly_report_404s_for_a_farm(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 404


async def test_weekly_report_includes_period_and_data_within_it(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    within_period = datetime.now(UTC) - timedelta(days=3)
    outside_period = datetime.now(UTC) - timedelta(days=20)
    with session_scope() as session:
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=talhao_id,
                event_type=AlertEventType.DRY_SPELL_WARNING,
                level=RiskLevel.ORANGE,
                title="Sequência sem chuva",
                message="7 dias consecutivos sem chuva mensurável.",
                dedup_key=f"{talhao_id}:{uuid.uuid4().hex}:dry_spell_warning",
                created_at=within_period,
            )
        )
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=talhao_id,
                event_type=AlertEventType.DRY_SPELL_WARNING,
                level=RiskLevel.ORANGE,
                title="Sequência sem chuva (antiga)",
                message="Fora do período do relatório.",
                dedup_key=f"{talhao_id}:{uuid.uuid4().hex}:dry_spell_warning",
                created_at=outside_period,
            )
        )
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=within_period,
                ndvi_mean=0.55,
                valid_pixel_percent=88.0,
                is_mock=True,
            )
        )
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=outside_period,
                ndvi_mean=0.10,
                valid_pixel_percent=70.0,
                is_mock=True,
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["location_name"] == "Talhão"
    assert body["crop"] == "soja"
    assert body["rainfall_total_mm"] >= 0
    assert 0 <= body["dry_days_count"] <= 7

    alert_titles = [a["title"] for a in body["alerts"]]
    assert "Sequência sem chuva" in alert_titles
    assert "Sequência sem chuva (antiga)" not in alert_titles

    ndvi_values = [n["ndvi_mean"] for n in body["ndvi_readings"]]
    assert 0.55 in ndvi_values
    assert 0.10 not in ndvi_values


async def test_weekly_report_another_users_talhao_is_404(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers_b)
    assert resp.status_code == 404
