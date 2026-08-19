"""Integration tests for /api/v1/public/* — visitor mode (FASE 15).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
conftest.py). The whole point of these endpoints is that they work
*without* any Authorization header.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

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
