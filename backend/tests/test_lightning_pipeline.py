"""Tests for the lightning-strike detection pipeline (FASE 23).

``parse_stsc_points`` is pure (no I/O) and unit-tested directly against the
real response shape documented by DECEA. The persistence path
(``run_lightning_detection_cycle``) needs a real Postgres — same pattern as
``test_agro_pipeline.py``: rolled back at the end, never committed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.lightning.models import LightningStrike
from workers.db import session_scope
from workers.lightning_pipeline import parse_stsc_points, run_lightning_detection_cycle

pytestmark = pytest.mark.integration

# Real shape from DECEA's docs (API-REDEMET: Produtos STSC).
_REAL_PAYLOAD = {
    "status": True,
    "message": 200,
    "data": {
        "info": {"tipo": "3", "topo": 999, "raio": 5560},
        "anima": ["14:58"],
        "stsc": [
            [
                {"la": "-23.05", "lo": "-33.45"},
                {"la": "-22.95", "lo": "-34.05"},
            ]
        ],
    },
}


def test_parse_stsc_points_reads_the_last_frame() -> None:
    payload = {
        "data": {
            "stsc": [
                [{"la": "-10.0", "lo": "-40.0"}],  # older frame — ignored
                [{"la": "-23.05", "lo": "-33.45"}, {"la": "-22.95", "lo": "-34.05"}],
            ]
        }
    }
    points = parse_stsc_points(payload)
    assert points == [(-23.05, -33.45), (-22.95, -34.05)]


def test_parse_stsc_points_real_shape() -> None:
    assert parse_stsc_points(_REAL_PAYLOAD) == [(-23.05, -33.45), (-22.95, -34.05)]


def test_parse_stsc_points_empty_when_no_frames() -> None:
    assert parse_stsc_points({"data": {"stsc": []}}) == []
    assert parse_stsc_points({"data": {}}) == []
    assert parse_stsc_points({}) == []


def test_parse_stsc_points_skips_malformed_entries() -> None:
    payload = {"data": {"stsc": [[{"la": "not-a-number", "lo": "-33.45"}, {"la": "1.0"}]]}}
    assert parse_stsc_points(payload) == []


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.closed = False

    def get(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(self._payload)

    def close(self) -> None:
        self.closed = True


def test_cycle_is_a_noop_when_disabled() -> None:
    with session_scope() as session:
        summary = run_lightning_detection_cycle(
            session, settings=Settings(environment="test", lightning_enabled=False)
        )
        assert summary.enabled is False
        assert summary.points_fetched == 0
        session.rollback()


def test_cycle_is_a_noop_without_api_key() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", lightning_enabled=True, redemet_api_key=None)
        summary = run_lightning_detection_cycle(session, settings=settings)
        assert summary.enabled is True
        assert summary.points_fetched == 0
        session.rollback()


def test_cycle_persists_fetched_points() -> None:
    with session_scope() as session:
        settings = Settings(
            environment="test", lightning_enabled=True, redemet_api_key="fake-key-for-test"
        )
        client = _FakeClient(_REAL_PAYLOAD)

        summary = run_lightning_detection_cycle(session, settings=settings, client=client)  # type: ignore[arg-type]

        assert summary.points_fetched == 2
        stored = session.scalars(
            select(LightningStrike).where(LightningStrike.longitude == -33.45)
        ).all()
        assert len(stored) == 1
        assert stored[0].latitude == -23.05
        session.rollback()


def test_cycle_prunes_stale_strikes() -> None:
    with session_scope() as session:
        old = LightningStrike(
            detected_at=datetime.now(UTC) - timedelta(hours=2),
            latitude=-10.0,
            longitude=-40.0,
            is_mock=False,
        )
        session.add(old)
        session.flush()
        old_id = old.id

        settings = Settings(
            environment="test",
            lightning_enabled=True,
            redemet_api_key="fake-key-for-test",
            lightning_retention_minutes=30.0,
        )
        client = _FakeClient({"data": {"stsc": []}})

        run_lightning_detection_cycle(session, settings=settings, client=client)  # type: ignore[arg-type]

        remaining = session.get(LightningStrike, old_id)
        assert remaining is None
        session.rollback()
