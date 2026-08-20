"""Integration tests for location CRUD + tenant isolation (FASE 14).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
``conftest.py``). Mirrors the "Integration — location CRUD + PostGIS nearby"
step already exercised via curl in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

_PAYLOAD = {
    "name": "Casa",
    "kind": "home",
    "latitude": -23.55,
    "longitude": -46.63,
    "radius_km": 50,
    "alert_preferences": [{"alert_type": "hail", "enabled": True}],
}


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def test_create_location_returns_201(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Casa"
    assert body["alert_preferences"] == [{"alert_type": "hail", "enabled": True}]


async def test_list_locations_includes_created_one(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.get("/api/v1/locations", headers=headers)
    assert resp.status_code == 200
    ids = [loc["id"] for loc in resp.json()]
    assert created["id"] in ids


async def test_get_update_delete_location_roundtrip(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()
    location_id = created["id"]

    get_resp = await client.get(f"/api/v1/locations/{location_id}", headers=headers)
    assert get_resp.status_code == 200

    update_resp = await client.put(
        f"/api/v1/locations/{location_id}", json={"name": "Trabalho"}, headers=headers
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Trabalho"

    delete_resp = await client.delete(f"/api/v1/locations/{location_id}", headers=headers)
    assert delete_resp.status_code == 204

    after_delete = await client.get(f"/api/v1/locations/{location_id}", headers=headers)
    assert after_delete.status_code == 404


async def test_get_unknown_location_returns_404(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_location_is_isolated_by_tenant(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=owner_headers)).json()
    location_id = created["id"]

    other_headers = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{location_id}", headers=other_headers)
    assert resp.status_code == 404

    resp = await client.put(
        f"/api/v1/locations/{location_id}", json={"name": "Hijack"}, headers=other_headers
    )
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/locations/{location_id}", headers=other_headers)
    assert resp.status_code == 404


async def test_risk_before_any_pipeline_cycle_returns_404(client: AsyncClient) -> None:
    # Deliberately far from the mock storm's fixed footprint (~-23.5,-46.6):
    # any pipeline cycle from an earlier local run — this session's pipeline
    # test always runs *after* this one, but a persistent local dev DB can
    # carry cells from a previous invocation — must not spuriously match.
    remote_payload = {**_PAYLOAD, "latitude": -3.1, "longitude": -60.0, "radius_km": 10}
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=remote_payload, headers=headers)).json()

    resp = await client.get(f"/api/v1/locations/{created['id']}/risk", headers=headers)
    assert resp.status_code == 404


async def test_storms_nearby_runs_postgis_query(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    resp = await client.get(
        "/api/v1/storms/nearby",
        params={"lat": -23.55, "lon": -46.63, "radius_km": 50},
        headers=headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_current_conditions_returns_live_reading(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.get(f"/api/v1/locations/{created['id']}/current", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "temperature_c" in body
    assert body["provenance"]["is_mock"] is True


async def test_spray_window_returns_live_wind_check(client: AsyncClient) -> None:
    # The shared `client` fixture's Settings default to the mock provider,
    # which always answers — exercises the success path (see
    # test_weather_mock.py for the honest-404 path via a failing provider).
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.get(f"/api/v1/locations/{created['id']}/agro/spray-window", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "safe" in body
    assert body["max_wind_kmh"] > 0


async def test_rainfall_history_returns_daily_totals(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.get(
        f"/api/v1/locations/{created['id']}/agro/rainfall",
        params={"days": 5},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["daily"]) == 5
