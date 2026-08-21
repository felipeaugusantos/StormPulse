"""Integration tests for location CRUD + tenant isolation (FASE 14).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
``conftest.py``). Mirrors the "Integration — location CRUD + PostGIS nearby"
step already exercised via curl in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import json
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


async def test_create_plot_under_a_farm(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    plot_payload = {
        **_PAYLOAD,
        "name": "Talhão 1",
        "parent_location_id": farm["id"],
        "crop": "soja",
    }
    resp = await client.post("/api/v1/locations", json=plot_payload, headers=headers)

    assert resp.status_code == 201
    body = resp.json()
    assert body["parent_location_id"] == farm["id"]
    assert body["crop"] == "soja"


async def test_plot_cannot_be_nested_under_another_plot(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()
    plot = (
        await client.post(
            "/api/v1/locations",
            json={**_PAYLOAD, "name": "Talhão 1", "parent_location_id": farm["id"]},
            headers=headers,
        )
    ).json()

    resp = await client.post(
        "/api/v1/locations",
        json={**_PAYLOAD, "name": "Talhão 1.1", "parent_location_id": plot["id"]},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_plot_cannot_use_another_tenants_location_as_parent(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=owner_headers)).json()

    other_headers = await _auth_headers(client)
    resp = await client.post(
        "/api/v1/locations",
        json={**_PAYLOAD, "name": "Talhão invasor", "parent_location_id": farm["id"]},
        headers=other_headers,
    )
    assert resp.status_code == 404


async def test_deleting_a_farm_cascades_to_its_plots(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()
    plot = (
        await client.post(
            "/api/v1/locations",
            json={**_PAYLOAD, "name": "Talhão 1", "parent_location_id": farm["id"]},
            headers=headers,
        )
    ).json()

    delete_resp = await client.delete(f"/api/v1/locations/{farm['id']}", headers=headers)
    assert delete_resp.status_code == 204

    resp = await client.get(f"/api/v1/locations/{plot['id']}", headers=headers)
    assert resp.status_code == 404


async def test_create_plot_with_boundary_polygon(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    boundary = {
        "type": "Polygon",
        "coordinates": [[[-47.81, -21.18], [-47.80, -21.18], [-47.80, -21.17], [-47.81, -21.18]]],
    }

    resp = await client.post(
        "/api/v1/locations",
        json={
            **_PAYLOAD,
            "name": "Talhão com contorno",
            "parent_location_id": farm["id"],
            "boundary_geojson": json.dumps(boundary),
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert json.loads(body["boundary_geojson"]) == boundary


async def test_create_location_rejects_malformed_boundary_geojson(client: AsyncClient) -> None:
    headers = await _auth_headers(client)

    resp = await client.post(
        "/api/v1/locations",
        json={**_PAYLOAD, "boundary_geojson": "not json"},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/v1/locations",
        json={**_PAYLOAD, "boundary_geojson": '{"type": "Point", "coordinates": [1, 2]}'},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/v1/locations",
        json={
            **_PAYLOAD,
            "boundary_geojson": '{"type": "Polygon", "coordinates": [[[-47.8, -21.1]]]}',
        },
        headers=headers,
    )
    assert resp.status_code == 422


async def test_create_plot_with_manual_color_override(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.post(
        "/api/v1/locations",
        json={
            **_PAYLOAD,
            "name": "Talhão colorido",
            "parent_location_id": farm["id"],
            "crop": "soja",
            "color": "#ff00aa",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["color"] == "#ff00aa"


async def test_create_location_rejects_malformed_color(client: AsyncClient) -> None:
    headers = await _auth_headers(client)

    resp = await client.post(
        "/api/v1/locations", json={**_PAYLOAD, "color": "not-a-color"}, headers=headers
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/v1/locations", json={**_PAYLOAD, "color": "#fff"}, headers=headers
    )
    assert resp.status_code == 422


async def test_update_location_color(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.put(
        f"/api/v1/locations/{created['id']}", json={"color": "#00ff00"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["color"] == "#00ff00"


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


async def test_rain_forecast_returns_live_points(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    created = (await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)).json()

    resp = await client.get(
        f"/api/v1/locations/{created['id']}/agro/rain-forecast", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["points"]) > 0


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
