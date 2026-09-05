"""Integration tests for GET /locations/{id}/forecast-comparison (Fase 2,
ADR-0082).

The location is created through the real API (auth + tenant isolation
exercised the normal way); the `ForecastSnapshot` rows behind the endpoint
are seeded directly with the sync worker session — same split as
``test_admin_validation.py``: this test exercises the read/aggregation
path, not the daily collection jobs (covered in
``test_forecast_comparison_pipeline.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.forecast_comparison.models import ForecastSnapshot
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration

_PAYLOAD = {
    "name": "Fazenda (teste comparação)",
    "kind": "farm",
    "latitude": -21.1775,
    "longitude": -47.8103,
    "radius_km": 50,
}


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_location(client: AsyncClient, headers: dict[str, str]) -> uuid.UUID:
    resp = await client.post("/api/v1/locations", json=_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


def _seed_snapshot(
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    model: str,
    target_date: date,
    temperature_predicted_c: float,
    temperature_observed_c: float,
    rain_predicted_mm: float = 0.0,
    rain_observed_mm: float = 0.0,
    observed: bool = True,
) -> None:
    with session_scope() as session:
        session.add(
            ForecastSnapshot(
                tenant_id=tenant_id,
                location_id=location_id,
                provider="Open-Meteo",
                model=model,
                target_date=target_date,
                horizon_hours=24,
                snapshot_taken_at=datetime.now(UTC) - timedelta(days=3),
                temperature_max_predicted_c=temperature_predicted_c,
                precipitation_predicted_mm=rain_predicted_mm,
                observed_at=datetime.now(UTC) if observed else None,
                temperature_max_observed_c=temperature_observed_c if observed else None,
                precipitation_observed_mm=rain_observed_mm if observed else None,
            )
        )


async def test_new_location_has_no_models_yet(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    resp = await client.get(f"/api/v1/locations/{location_id}/forecast-comparison", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["location_id"] == str(location_id)
    assert body["models"] == []


async def test_computes_metrics_from_observed_snapshots(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = await client.get("/api/v1/users/me", headers=headers)
    tenant_id = uuid.UUID(me.json()["tenant_id"])

    _seed_snapshot(
        tenant_id=tenant_id,
        location_id=location_id,
        model="ecmwf_ifs025",
        target_date=date(2026, 8, 1),
        temperature_predicted_c=30.0,
        temperature_observed_c=32.0,
        rain_predicted_mm=10.0,
        rain_observed_mm=5.0,
    )
    _seed_snapshot(
        tenant_id=tenant_id,
        location_id=location_id,
        model="ecmwf_ifs025",
        target_date=date(2026, 8, 2),
        temperature_predicted_c=28.0,
        temperature_observed_c=28.0,
        rain_predicted_mm=0.0,
        rain_observed_mm=0.0,
    )

    resp = await client.get(f"/api/v1/locations/{location_id}/forecast-comparison", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["models"]) == 1
    model = body["models"][0]
    assert model["model"] == "ecmwf_ifs025"
    assert model["sample_count"] == 2
    assert model["temperature_mae_c"] == 1.0  # (2.0 + 0.0) / 2
    assert model["precipitation"]["bias_mm"] == 2.5  # (+5, 0) / 2


async def test_has_enough_samples_flips_at_the_configured_minimum(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = await client.get("/api/v1/users/me", headers=headers)
    tenant_id = uuid.UUID(me.json()["tenant_id"])

    for i in range(3):
        _seed_snapshot(
            tenant_id=tenant_id,
            location_id=location_id,
            model="gfs_seamless",
            target_date=date(2026, 8, 1) + timedelta(days=i),
            temperature_predicted_c=25.0,
            temperature_observed_c=25.0,
        )

    resp = await client.get(f"/api/v1/locations/{location_id}/forecast-comparison", headers=headers)

    assert resp.status_code == 200
    model = resp.json()["models"][0]
    assert model["sample_count"] == 3
    # Default min_sample_size (engine.validation.MIN_SAMPLE_SIZE_FOR_RECOMMENDATION-
    # aligned default, 20) is well above 3 — must not be flagged reliable.
    assert model["has_enough_samples"] is False


async def test_ignores_snapshots_without_an_observation_yet(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = await client.get("/api/v1/users/me", headers=headers)
    tenant_id = uuid.UUID(me.json()["tenant_id"])

    _seed_snapshot(
        tenant_id=tenant_id,
        location_id=location_id,
        model="icon_seamless",
        target_date=date(2026, 8, 10),
        temperature_predicted_c=20.0,
        temperature_observed_c=0.0,
        observed=False,
    )

    resp = await client.get(f"/api/v1/locations/{location_id}/forecast-comparison", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["models"] == []


async def test_another_tenants_snapshots_never_leak_into_this_locations_comparison(
    client: AsyncClient,
) -> None:
    """Confirms the endpoint filters by `location_id` (not just tenant) —
    a snapshot for a *different* location must never contaminate this
    one's metrics, even for the same model name."""
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    other_headers = await _auth_headers(client)
    other_location_id = await _create_location(client, other_headers)
    other_me = await client.get("/api/v1/users/me", headers=other_headers)
    other_tenant_id = uuid.UUID(other_me.json()["tenant_id"])

    _seed_snapshot(
        tenant_id=other_tenant_id,
        location_id=other_location_id,
        model="ecmwf_ifs025",
        target_date=date(2026, 8, 1),
        temperature_predicted_c=99.0,
        temperature_observed_c=99.0,
    )

    resp = await client.get(f"/api/v1/locations/{location_id}/forecast-comparison", headers=headers)

    assert resp.status_code == 200
    assert resp.json()["models"] == []
