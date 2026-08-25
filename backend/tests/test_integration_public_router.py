"""Integration tests for /api/v1/public/* — visitor mode (FASE 15).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
conftest.py). The whole point of these endpoints is that they work
*without* any Authorization header.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from geoalchemy2.elements import WKTElement
from httpx import AsyncClient
from sqlalchemy import select

from app.lightning.models import LightningStrike
from app.satellite.models import ConvectiveWatch, SatelliteImage
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


async def test_public_satellite_watches_nearby_works_without_auth_and_filters_by_distance(
    client: AsyncClient,
) -> None:
    # FASE 34 bug report: visitor mode picked a location but the satellite
    # watches panel never actually filtered by it — this endpoint is the
    # fix, so it must both work anonymously and actually apply the radius.
    now = datetime.now(UTC)
    with session_scope() as session:
        near = ConvectiveWatch(
            first_detected_at=now,
            detected_at=now,
            latitude=-23.5,
            longitude=-46.6,
            centroid=WKTElement("POINT(-46.6 -23.5)", srid=4326),
            min_brightness_temp_k=210.0,
            is_active=True,
            is_mock=False,
            experimental=True,
        )
        far = ConvectiveWatch(
            first_detected_at=now,
            detected_at=now,
            latitude=5.0,
            longitude=-70.0,
            centroid=WKTElement("POINT(-70.0 5.0)", srid=4326),
            min_brightness_temp_k=210.0,
            is_active=True,
            is_mock=False,
            experimental=True,
        )
        session.add_all([near, far])
        session.flush()
        near_id = near.id

    resp = await client.get(
        "/api/v1/public/satellite/watches/nearby",
        params={"lat": -23.5, "lon": -46.6, "radius_km": 50},
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body}
    assert str(near_id) in ids
    assert all(item["distance_km"] < 50 for item in body)

    with session_scope() as session:
        for stale in session.scalars(select(ConvectiveWatch)).all():
            session.delete(stale)


async def test_public_lightning_nearby_works_without_auth_and_filters_by_distance(
    client: AsyncClient,
) -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        near = LightningStrike(detected_at=now, latitude=-23.5, longitude=-46.6, is_mock=False)
        far = LightningStrike(detected_at=now, latitude=5.0, longitude=-70.0, is_mock=False)
        session.add_all([near, far])
        session.flush()
        near_id = near.id

    resp = await client.get(
        "/api/v1/public/lightning/nearby",
        params={"lat": -23.5, "lon": -46.6, "radius_km": 50},
    )
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body}
    assert str(near_id) in ids
    assert all(item["distance_km"] < 50 for item in body)

    with session_scope() as session:
        for stale in session.scalars(select(LightningStrike)).all():
            session.delete(stale)


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
