"""Integration tests for /api/v1/public/* — visitor mode (FASE 15).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
conftest.py). The whole point of these endpoints is that they work
*without* any Authorization header.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.satellite.models import SatelliteImage
from workers.db import session_scope

pytestmark = pytest.mark.integration


async def test_public_storms_works_without_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/storms")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_public_storms_nearby_works_without_auth(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/public/storms/nearby", params={"lat": -23.5, "lon": -46.6, "radius_km": 50}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_public_warnings_works_without_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/warnings", params={"lat": -23.5, "lon": -46.6})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_public_storms_never_returns_401(client: AsyncClient) -> None:
    # Sanity check against the exact regression this feature is about: a
    # visitor with no token must never be bounced to a login flow.
    resp = await client.get("/api/v1/public/storms")
    assert resp.status_code != 401


async def test_public_satellite_image_returns_404_when_none_exists(client: AsyncClient) -> None:
    # Honest 404, not a placeholder image, when no cycle has produced one
    # yet (or SATELLITE_ENABLED=false).
    with session_scope() as session:
        for stale in session.scalars(select(SatelliteImage)).all():
            session.delete(stale)

    resp = await client.get("/api/v1/public/satellite/image")
    assert resp.status_code == 404
    resp = await client.get("/api/v1/public/satellite/image.png")
    assert resp.status_code == 404


async def test_public_satellite_image_meta_and_png_work_without_auth(
    client: AsyncClient,
) -> None:
    captured_at = datetime.now(UTC)
    png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-decoded-png-but-fine-for-this-test"
    with session_scope() as session:
        for stale in session.scalars(select(SatelliteImage)).all():
            session.delete(stale)
        session.add(
            SatelliteImage(
                captured_at=captured_at,
                bbox_lon_min=-74.0,
                bbox_lat_min=-34.0,
                bbox_lon_max=-34.0,
                bbox_lat_max=6.0,
                band="B13",
                width=10,
                height=8,
                png_data=png_bytes,
                is_mock=False,
                experimental=True,
            )
        )

    meta_resp = await client.get("/api/v1/public/satellite/image")
    assert meta_resp.status_code == 200
    body = meta_resp.json()
    assert body["bbox"] == [-74.0, -34.0, -34.0, 6.0]
    assert body["band"] == "B13"
    assert body["width"] == 10
    assert body["height"] == 8

    png_resp = await client.get("/api/v1/public/satellite/image.png")
    assert png_resp.status_code == 200
    assert png_resp.headers["content-type"] == "image/png"
    assert png_resp.content == png_bytes

    with session_scope() as session:
        for stale in session.scalars(select(SatelliteImage)).all():
            session.delete(stale)
