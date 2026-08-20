"""Integration tests for the lightning-strike read endpoints (FASE 23).

Global data (no tenant_id) — same reasoning as storms/satellite: any
authenticated user sees the same rows, and the public endpoint mirrors that
with no auth at all. Rows are seeded directly via the owner-role sync
session (``session_scope``) and cleaned up at the end, since these
endpoints only read via the async session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.lightning.models import LightningStrike
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


def _seed_strike() -> uuid.UUID:
    with session_scope() as session:
        strike = LightningStrike(
            detected_at=datetime.now(UTC), latitude=-23.5, longitude=-46.6, is_mock=False
        )
        session.add(strike)
        session.flush()
        strike_id = strike.id
    return strike_id


def _cleanup_strike(strike_id: uuid.UUID) -> None:
    with session_scope() as session:
        row = session.get(LightningStrike, strike_id)
        if row is not None:
            session.delete(row)


async def test_authenticated_lightning_endpoint_returns_seeded_strike(
    client: AsyncClient,
) -> None:
    strike_id = _seed_strike()
    try:
        token = await register_and_login(client)
        resp = await client.get("/api/v1/lightning", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        ids = [row["id"] for row in resp.json()]
        assert str(strike_id) in ids
    finally:
        _cleanup_strike(strike_id)


async def test_lightning_endpoint_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/lightning")
    assert resp.status_code == 401


async def test_public_lightning_endpoint_returns_seeded_strike(client: AsyncClient) -> None:
    strike_id = _seed_strike()
    try:
        resp = await client.get("/api/v1/public/lightning")
        assert resp.status_code == 200
        ids = [row["id"] for row in resp.json()]
        assert str(strike_id) in ids
    finally:
        _cleanup_strike(strike_id)
