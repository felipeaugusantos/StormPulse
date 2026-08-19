"""Tests for tracking association and trajectory/ETA estimation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.enums import StormSeverity, TrackTrend
from engine.detection.detector import DetectedCell
from engine.tracking.tracker import Track, TrackBuilder
from engine.trajectory.estimator import estimate_trajectory, eta_minutes_to

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _cell(lat: float, lon: float, minute: int, dbz: float = 50.0) -> DetectedCell:
    return DetectedCell(
        detected_at=T0 + timedelta(minutes=minute),
        latitude=lat,
        longitude=lon,
        max_reflectivity=dbz,
        average_reflectivity=dbz - 10,
        area_km2=40.0,
        severity=StormSeverity.STRONG,
        is_mock=True,
    )


def test_tracking_associates_close_cells() -> None:
    # Same cell drifting north over two frames → one track with two observations.
    frames = [[_cell(-24.0, -46.6, 0)], [_cell(-23.9, -46.6, 5)]]
    tracks = TrackBuilder().build(frames)
    assert len(tracks) == 1
    assert len(tracks[0].observations) == 2


def test_tracking_splits_distant_cells() -> None:
    frames = [[_cell(-24.0, -46.6, 0)], [_cell(-10.0, -40.0, 5)]]
    tracks = TrackBuilder().build(frames)
    assert len(tracks) == 2


def test_trajectory_needs_two_observations() -> None:
    track = Track(observations=[_cell(-24.0, -46.6, 0)])
    assert estimate_trajectory(track) is None


def test_trajectory_speed_and_direction_northbound() -> None:
    # ~11.1 km north in 5 min → ~133 km/h, heading N.
    track = Track(observations=[_cell(-24.0, -46.6, 0), _cell(-23.9, -46.6, 5)])
    traj = estimate_trajectory(track)
    assert traj is not None
    assert 120 < traj.speed_kmh < 145
    assert traj.direction_label == "N"
    assert abs(traj.direction_deg) < 1 or abs(traj.direction_deg - 360) < 1


def test_trend_intensifying() -> None:
    track = Track(observations=[_cell(-24.0, -46.6, 0, dbz=40), _cell(-23.9, -46.6, 5, dbz=55)])
    traj = estimate_trajectory(track)
    assert traj is not None
    assert traj.trend is TrackTrend.INTENSIFYING


def test_eta_toward_target_is_positive() -> None:
    # Storm south of target moving north straight at it.
    track = Track(observations=[_cell(-24.0, -46.6, 0), _cell(-23.9, -46.6, 5)])
    traj = estimate_trajectory(track)
    assert traj is not None
    eta = eta_minutes_to(
        traj, current_lat=-23.9, current_lon=-46.6, target_lat=-23.5, target_lon=-46.6
    )
    assert eta is not None and eta > 0


def test_eta_none_when_moving_away() -> None:
    track = Track(observations=[_cell(-24.0, -46.6, 0), _cell(-23.9, -46.6, 5)])
    traj = estimate_trajectory(track)
    assert traj is not None
    # Target is to the south (behind); storm heads north → no ETA.
    eta = eta_minutes_to(
        traj, current_lat=-23.9, current_lon=-46.6, target_lat=-24.5, target_lon=-46.6
    )
    assert eta is None


def test_eta_none_when_stationary() -> None:
    track = Track(observations=[_cell(-24.0, -46.6, 0), _cell(-24.0, -46.6, 5)])
    traj = estimate_trajectory(track)
    assert traj is not None
    eta = eta_minutes_to(
        traj, current_lat=-24.0, current_lon=-46.6, target_lat=-23.5, target_lon=-46.6
    )
    assert eta is None
