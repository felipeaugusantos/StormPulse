"""Tests for the 1h motion projection added to StormCellOut (item "previsão
de 1h" — reuses the speed/direction already computed per observation by
engine/trajectory/estimator.py, never a second forecast model).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.core.enums import StormSeverity
from app.storms import service
from app.storms.models import StormCell, StormObservation, StormTrack
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


def _make_cell_with_track(
    session_scope_session: Session,
    *,
    active: bool,
    speed_kmh: float | None,
    direction_deg: float | None,
) -> StormCell:
    now = datetime.now(UTC)
    cell = StormCell(
        detected_at=now,
        latitude=-23.5,
        longitude=-46.6,
        severity=StormSeverity.MODERATE,
        is_mock=True,
    )
    session_scope_session.add(cell)
    session_scope_session.flush()
    track = StormTrack(
        storm_cell_id=cell.id,
        started_at=now - timedelta(minutes=10),
        last_observed_at=now,
        is_active=active,
    )
    session_scope_session.add(track)
    session_scope_session.flush()
    session_scope_session.add(
        StormObservation(
            storm_track_id=track.id,
            observed_at=now - timedelta(minutes=5),
            latitude=-23.6,
            longitude=-46.7,
        )
    )
    session_scope_session.add(
        StormObservation(
            storm_track_id=track.id,
            observed_at=now,
            latitude=-23.5,
            longitude=-46.6,
            speed_kmh=speed_kmh,
            direction_deg=direction_deg,
        )
    )
    session_scope_session.flush()
    session_scope_session.refresh(cell)
    return cell


def test_projects_1h_ahead_from_the_active_tracks_latest_observation() -> None:
    with session_scope() as session:
        cell = _make_cell_with_track(session, active=True, speed_kmh=30.0, direction_deg=0.0)
        # Force-load relationships while the sync session is still open —
        # to_storm_cell_out only reads already-loaded attributes.
        _ = [t.observations for t in cell.tracks]

        out = service.to_storm_cell_out(cell)

        assert out.speed_kmh == 30.0
        assert out.direction_deg == 0.0
        assert out.projected_latitude_1h is not None
        assert out.projected_longitude_1h is not None
        # Heading due north (0°) at 30 km/h for 1h: latitude increases,
        # longitude essentially unchanged.
        assert out.projected_latitude_1h > cell.latitude
        assert out.projected_longitude_1h == pytest.approx(cell.longitude, abs=0.01)
        session.rollback()


def test_no_projection_when_the_track_has_no_computed_trajectory_yet() -> None:
    """Fewer than 2 real observations means estimate_trajectory (and thus
    speed/direction) was never computed — must never fabricate one here."""
    with session_scope() as session:
        cell = _make_cell_with_track(session, active=True, speed_kmh=None, direction_deg=None)
        _ = [t.observations for t in cell.tracks]

        out = service.to_storm_cell_out(cell)

        assert out.speed_kmh is None
        assert out.direction_deg is None
        assert out.projected_latitude_1h is None
        assert out.projected_longitude_1h is None
        session.rollback()


def test_no_projection_from_a_dissipated_inactive_track() -> None:
    """A track's last known motion goes stale the moment the storm
    dissipates — never used to project a position for a storm that's gone."""
    with session_scope() as session:
        cell = _make_cell_with_track(session, active=False, speed_kmh=25.0, direction_deg=90.0)
        _ = [t.observations for t in cell.tracks]

        out = service.to_storm_cell_out(cell)

        assert out.speed_kmh is None
        assert out.projected_latitude_1h is None
        session.rollback()


async def test_storms_endpoint_includes_the_projection(client: AsyncClient) -> None:
    """End-to-end through the real async router/service — catches a lazy-
    load regression (async SQLAlchemy raises on unloaded relationships)
    that a pure in-memory test of to_storm_cell_out alone wouldn't."""
    token = await register_and_login(client)
    with session_scope() as session:
        cell = _make_cell_with_track(session, active=True, speed_kmh=20.0, direction_deg=180.0)
        cell_id = cell.id
        session.commit()

    try:
        resp = await client.get(
            f"/api/v1/storms/{cell_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["speed_kmh"] == 20.0
        assert body["direction_deg"] == 180.0
        assert body["projected_latitude_1h"] is not None
        assert body["projected_longitude_1h"] is not None
    finally:
        with session_scope() as session:
            db_cell = session.get(StormCell, cell_id)
            if db_cell is not None:
                session.delete(db_cell)
