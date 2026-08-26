"""Integration tests for the weekly-report PDF endpoint (item 2, ADR-0063).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Reuses the same farm/talhão setup as ``test_integration_weekly_report.py``.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

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


async def test_weekly_report_pdf_returns_a_real_pdf(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(
        f"/api/v1/locations/{talhao_id}/agro/weekly-report/pdf", headers=headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")


async def test_weekly_report_pdf_404s_for_a_farm(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/weekly-report/pdf", headers=headers)
    assert resp.status_code == 404


async def test_weekly_report_pdf_another_users_talhao_is_404(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(
        f"/api/v1/locations/{talhao_id}/agro/weekly-report/pdf", headers=headers_b
    )
    assert resp.status_code == 404


async def test_weekly_report_pdf_requires_auth(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report/pdf")
    assert resp.status_code == 401
