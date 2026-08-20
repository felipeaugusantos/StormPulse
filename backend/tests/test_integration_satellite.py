"""Integration tests for the satellite pipeline's DB-touching logic (FASE 16).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
conftest.py). Exercises ``_match_or_create``/``_decide_alerts`` directly with
synthetic ``DetectedSystem`` values — the GDAL-dependent detection step
itself (``_detect_systems``) is verified manually against real satellite
data (see ADR-0009), not here.

Everything (tenant/user/location included) is built directly in the sync
session used by the pipeline and rolled back at the end of each test — no
row here is ever committed, so repeated runs never pollute the shared dev
database (unlike going through the real HTTP API, which commits for real).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.enums import AlertEventType
from app.locations.models import Location
from app.satellite.models import ConvectiveWatch
from app.tenants.models import Tenant
from app.users.models import User
from workers.db import session_scope
from workers.satellite_pipeline import (
    DetectedSystem,
    _decide_alerts,
    _match_or_create,
    _prune_stale_watches,
)

pytestmark = pytest.mark.integration


def _make_location(
    session: Session, *, latitude: float, longitude: float, radius_km: float
) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"sat-{unique}@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(user)
    session.flush()
    location = Location(
        tenant_id=tenant.id,
        user_id=user.id,
        name="Perto do satélite (teste)",
        kind="other",
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        is_active=True,
    )
    session.add(location)
    session.flush()
    return location


def _system(lat: float, lon: float, *, temp_k: float = 210.0) -> DetectedSystem:
    # ConvectiveWatch.geometry is a POLYGON column (real TATHU systems are
    # always polygons) — a tiny square around the centroid, not a point.
    d = 0.01
    ring = (
        f"{lon - d} {lat - d}, {lon + d} {lat - d}, "
        f"{lon + d} {lat + d}, {lon - d} {lat + d}, {lon - d} {lat - d}"
    )
    return DetectedSystem(
        latitude=lat,
        longitude=lon,
        geometry_wkt=f"POLYGON(({ring}))",
        min_brightness_temp_k=temp_k,
        area_km2=5000.0,
    )


def test_new_system_creates_watch_and_alerts_nearby_location() -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        location = _make_location(session, latitude=-8.0, longitude=-63.0, radius_km=100)

        touched, dissipated = _match_or_create(session, [_system(-8.05, -63.05)], now)
        session.flush()
        assert len(touched) == 1
        watch_id = touched[0].id
        # Not asserting dissipated == [] here: the shared dev DB may carry
        # real watches from earlier manual verification runs (kept
        # deliberately, for the dashboard demo) that this detection pass
        # legitimately doesn't re-detect — that's correct behavior, not
        # something this test should depend on being absent.
        assert watch_id not in {w.id for w in dissipated}

        alerts = _decide_alerts(session, touched, dissipated)
        assert alerts == 1

        alert = session.scalars(select(Alert).where(Alert.convective_watch_id == watch_id)).one()
        assert alert.event_type == AlertEventType.SATELLITE_WATCH_DETECTED
        assert alert.location_id == location.id
        session.rollback()


def test_matching_system_updates_existing_watch_not_duplicate() -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        touched1, _ = _match_or_create(session, [_system(-9.0, -64.0)], now)
        session.flush()
        watch_id = touched1[0].id

        later = now + timedelta(minutes=10)
        # Slightly moved, but well within the matching radius.
        touched2, dissipated2 = _match_or_create(session, [_system(-9.05, -64.05)], later)
        session.flush()

        assert dissipated2 == []
        assert len(touched2) == 1
        assert touched2[0].id == watch_id  # same row updated, not a new one
        assert touched2[0].speed_kmh is not None  # two observations -> velocity known
        session.rollback()


def test_unmatched_active_watch_becomes_dissipated() -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        touched1, _ = _match_or_create(session, [_system(-10.0, -65.0)], now)
        session.flush()
        watch_id = touched1[0].id

        # Nothing detected nearby anymore -> the watch should dissipate.
        later = now + timedelta(minutes=10)
        touched2, dissipated2 = _match_or_create(session, [], later)
        session.flush()

        assert touched2 == []
        assert [w.id for w in dissipated2] == [watch_id]
        assert dissipated2[0].is_active is False
        session.rollback()


def test_alert_emission_is_idempotent() -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        _make_location(session, latitude=-8.0, longitude=-63.0, radius_km=100)

        touched, _ = _match_or_create(session, [_system(-8.02, -63.02)], now)
        session.flush()
        first = _decide_alerts(session, touched, [])
        session.flush()
        # Re-running the exact same decision must not double-alert.
        second = _decide_alerts(session, touched, [])
        assert first == 1
        assert second == 0
        session.rollback()


def test_prune_stale_watches_removes_old_inactive_rows() -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        watch = ConvectiveWatch(
            first_detected_at=now - timedelta(hours=10),
            detected_at=now - timedelta(hours=10),
            latitude=-11.0,
            longitude=-66.0,
            min_brightness_temp_k=225.0,
            is_active=False,
            is_mock=False,
            experimental=True,
        )
        session.add(watch)
        session.flush()
        watch_id = watch.id

        _prune_stale_watches(session, older_than=timedelta(hours=3))
        session.flush()

        remaining = session.get(ConvectiveWatch, watch_id)
        assert remaining is None
        session.rollback()
