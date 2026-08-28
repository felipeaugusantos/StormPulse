"""Integration tests for the deforestation-check endpoint (item DETER).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
The endpoint only ever reads what the pipeline already wrote, so these
insert ``DeforestationCheck`` rows directly via the sync workers session
(same DB, same pattern ``test_integration_ndvi.py`` uses) rather than
running a real INPE-backed pipeline cycle.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.deforestation.models import DeforestationCheck
from app.deforestation.provider import DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE
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
                "boundary_geojson": _BOUNDARY,
            },
            headers=headers,
        )
    ).json()
    return farm["id"], talhao["id"]


async def test_no_check_yet_returns_404(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/deforestation", headers=headers)
    assert resp.status_code == 404


async def test_farm_without_boundary_404s_with_the_talhao_only_message(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/deforestation", headers=headers)
    assert resp.status_code == 404
    assert "talhões" in resp.json()["detail"]


async def test_returns_alerts_merged_from_both_sources(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    now = datetime.now(UTC)
    with session_scope() as session:
        session.add(
            DeforestationCheck(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                source=DETER_AMZ_SOURCE,
                checked_at=now,
                alert_count=1,
                alerts_json=json.dumps(
                    [
                        {
                            "source": DETER_AMZ_SOURCE,
                            "classname": "DESMATAMENTO_CR",
                            "detected_at": "2026-07-01",
                            "area_ha": 12.5,
                            "municipio": "obidos",
                            "uf": "PA",
                        }
                    ]
                ),
            )
        )
        session.add(
            DeforestationCheck(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                source=PRODES_CERRADO_SOURCE,
                checked_at=now,
                alert_count=0,
                alerts_json="[]",
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/deforestation", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["checked_sources"]) == {DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE}
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["classname"] == "DESMATAMENTO_CR"
    assert body["alerts"][0]["area_ha"] == 12.5


async def test_another_users_check_is_404_not_someone_elses_data(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)
    me_a = (await client.get("/api/v1/users/me", headers=headers_a)).json()

    with session_scope() as session:
        session.add(
            DeforestationCheck(
                tenant_id=me_a["tenant_id"],
                location_id=talhao_id,
                source=DETER_AMZ_SOURCE,
                checked_at=datetime.now(UTC),
                alert_count=0,
                alerts_json="[]",
            )
        )

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/deforestation", headers=headers_b)
    assert resp.status_code == 404


async def test_weekly_report_includes_deforestation_when_checked(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            DeforestationCheck(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                source=DETER_AMZ_SOURCE,
                checked_at=datetime.now(UTC),
                alert_count=0,
                alerts_json="[]",
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["deforestation"] is not None
    assert body["deforestation"]["checked_sources"] == [DETER_AMZ_SOURCE]


async def test_weekly_report_deforestation_is_null_when_never_checked(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deforestation"] is None
