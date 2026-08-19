"""Integration test for the ingestion pipeline materializing storms + risk.

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
``conftest.py``). Mirrors the "Integration — worker pipeline materializes
storms + risk" step already exercised via ``docker compose run ...
workers.run_once`` + curl in ``.github/workflows/ci.yml``, calling
``run_ingestion_cycle`` directly instead of shelling out.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login
from workers.db import session_scope
from workers.pipeline_service import CycleSummary, run_ingestion_cycle

pytestmark = pytest.mark.integration

# Matches MockWeatherProvider's fixed mock cell footprint (see
# backend/app/weather/mock.py) so the location falls within its radius.
_LOCATION_NEAR_MOCK_STORM = {
    "name": "Casa",
    "kind": "home",
    "latitude": -23.5,
    "longitude": -46.6,
    "radius_km": 80,
}


async def test_pipeline_cycle_materializes_storms_and_risk(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = (
        await client.post("/api/v1/locations", json=_LOCATION_NEAR_MOCK_STORM, headers=headers)
    ).json()
    location_id = created["id"]

    def _run_one_cycle() -> CycleSummary:
        # run_ingestion_cycle is synchronous and calls asyncio.run() itself
        # (as Celery's sync worker does) — it can't run on the loop this
        # async test is already on, so it gets its own thread instead.
        with session_scope() as session:
            return run_ingestion_cycle(session)

    summary = await asyncio.to_thread(_run_one_cycle)
    assert summary.cells >= 1
    assert summary.risks >= 1

    storms_resp = await client.get("/api/v1/storms", headers=headers)
    assert storms_resp.status_code == 200
    assert len(storms_resp.json()) >= 1

    nearby_resp = await client.get(
        "/api/v1/storms/nearby",
        params={"lat": -23.5, "lon": -46.6, "radius_km": 80},
        headers=headers,
    )
    assert nearby_resp.status_code == 200
    assert len(nearby_resp.json()) >= 1

    risk_resp = await client.get(f"/api/v1/locations/{location_id}/risk", headers=headers)
    assert risk_resp.status_code == 200
    risk = risk_resp.json()
    assert risk["is_mock"] is True
    assert risk["experimental"] is True
