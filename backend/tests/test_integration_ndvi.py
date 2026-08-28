"""Integration tests for the NDVI-per-talhão endpoint (FASE 29, ADR-0053).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
The endpoint only ever reads what the pipeline already wrote, so these
insert an `NdviReading` directly via the sync workers session (same DB,
same pattern `test_ndvi_pipeline.py` uses) rather than running a real
Copernicus-backed pipeline cycle.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.ndvi.models import NdviImage, NdviReading
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


async def test_no_reading_yet_returns_404(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi", headers=headers)
    assert resp.status_code == 404


async def test_farm_without_boundary_also_404s(client: AsyncClient) -> None:
    """The endpoint doesn't special-case "not a talhão" — it just never has
    a row for a location the pipeline never checks, same honest 404."""
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/ndvi", headers=headers)
    assert resp.status_code == 404


async def test_returns_the_most_recent_reading(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    older = datetime.now(UTC) - timedelta(days=5)
    newer = datetime.now(UTC) - timedelta(days=1)
    with session_scope() as session:
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=older,
                ndvi_mean=0.30,
                valid_pixel_percent=80.0,
                is_mock=True,
            )
        )
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=newer,
                ndvi_mean=0.71,
                valid_pixel_percent=95.0,
                is_mock=True,
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ndvi_mean"] == 0.71
    assert body["valid_pixel_percent"] == 95.0
    assert body["is_mock"] is True


async def test_another_users_talhao_is_404_not_someone_elses_data(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi", headers=headers_b)
    assert resp.status_code == 404


async def test_no_image_yet_returns_404(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi-image", headers=headers)
    assert resp.status_code == 404


async def test_returns_the_stored_ndvi_image(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    fake_png = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    with session_scope() as session:
        session.add(
            NdviImage(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=datetime.now(UTC),
                png_data=fake_png,
                is_mock=True,
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi-image", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == fake_png


async def test_another_users_ndvi_image_is_404(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/ndvi-image", headers=headers_b)
    assert resp.status_code == 404
