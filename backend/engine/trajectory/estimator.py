"""Trajectory estimation from a track (FASE 7).

From two or more observations, derive displacement, direction, speed and trend,
project a future position, and estimate ETA to a target using the closing-speed
(velocity component toward the target). This beats naive "distance / raw speed"
because a storm moving across, or away from, a location gets a correct
(or absent) ETA. Marked experimental until validated with real data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.enums import TrackTrend
from engine.config import DEFAULT_TRAJECTORY, TrajectoryConfig
from engine.geo import (
    angle_difference,
    bearing_deg,
    compass_label,
    destination_point,
    haversine_km,
)
from engine.tracking.tracker import Track


@dataclass(frozen=True)
class Trajectory:
    """Kinematic summary of a track's most recent motion."""

    speed_kmh: float
    direction_deg: float
    direction_label: str
    trend: TrackTrend
    experimental: bool = True

    def project_position(
        self, from_lat: float, from_lon: float, minutes: float
    ) -> tuple[float, float]:
        """Where the cell will be in ``minutes``, moving along its heading."""
        distance = self.speed_kmh * (minutes / 60.0)
        return destination_point(from_lat, from_lon, self.direction_deg, distance)


def _trend(track: Track, cfg: TrajectoryConfig) -> TrackTrend:
    first = track.observations[0].max_reflectivity or 0.0
    last = track.observations[-1].max_reflectivity or 0.0
    delta = last - first
    if delta >= cfg.trend_delta_dbz:
        return TrackTrend.INTENSIFYING
    if delta <= -cfg.trend_delta_dbz:
        return TrackTrend.WEAKENING
    return TrackTrend.STEADY


def estimate_trajectory(
    track: Track, config: TrajectoryConfig = DEFAULT_TRAJECTORY
) -> Trajectory | None:
    """Estimate current motion from the last two observations.

    Returns ``None`` when there are fewer than two observations (not enough
    data — we never fabricate a trajectory).
    """
    obs = track.observations
    if len(obs) < 2:
        return None

    prev, curr = obs[-2], obs[-1]
    dt_hours = (curr.detected_at - prev.detected_at).total_seconds() / 3600.0
    if dt_hours <= 0:
        return None

    distance = haversine_km(prev.latitude, prev.longitude, curr.latitude, curr.longitude)
    speed = distance / dt_hours
    direction = bearing_deg(prev.latitude, prev.longitude, curr.latitude, curr.longitude)

    return Trajectory(
        speed_kmh=round(speed, 2),
        direction_deg=round(direction, 1),
        direction_label=compass_label(direction),
        trend=_trend(track, config),
    )


def eta_minutes_to(
    trajectory: Trajectory,
    *,
    current_lat: float,
    current_lon: float,
    target_lat: float,
    target_lon: float,
    config: TrajectoryConfig = DEFAULT_TRAJECTORY,
) -> int | None:
    """ETA (minutes) for the cell to reach the target, via closing speed.

    Returns ``None`` when the cell is essentially stationary or not moving
    toward the target (no false ETA).
    """
    if trajectory.speed_kmh < config.min_speed_kmh:
        return None

    distance = haversine_km(current_lat, current_lon, target_lat, target_lon)
    bearing_to_target = bearing_deg(current_lat, current_lon, target_lat, target_lon)
    offset = angle_difference(trajectory.direction_deg, bearing_to_target)
    if offset >= 90.0:
        return None  # moving across or away from the target

    closing_speed = trajectory.speed_kmh * math.cos(math.radians(offset))
    if closing_speed < config.min_speed_kmh:
        return None
    return round(distance / closing_speed * 60.0)
