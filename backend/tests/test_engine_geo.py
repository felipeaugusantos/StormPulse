"""Tests for great-circle geometry helpers."""

from __future__ import annotations

import math

from engine.geo import (
    EARTH_RADIUS_KM,
    angle_difference,
    bearing_deg,
    compass_label,
    destination_point,
    haversine_km,
    polygon_area_km2,
)


def test_haversine_zero() -> None:
    assert haversine_km(-23.55, -46.63, -23.55, -46.63) == 0.0


def test_haversine_saopaulo_rio() -> None:
    # São Paulo ↔ Rio de Janeiro is ~360 km.
    d = haversine_km(-23.55, -46.63, -22.91, -43.17)
    assert 350 < d < 375


def test_bearing_cardinal_directions() -> None:
    assert abs(bearing_deg(0, 0, 1, 0) - 0.0) < 0.5  # north
    assert abs(bearing_deg(0, 0, 0, 1) - 90.0) < 0.5  # east
    assert abs(bearing_deg(0, 0, -1, 0) - 180.0) < 0.5  # south


def test_destination_point_roundtrip() -> None:
    lat, lon = destination_point(-23.5, -46.6, 90, 100)
    back = haversine_km(-23.5, -46.6, lat, lon)
    assert abs(back - 100) < 0.5


def test_compass_label_pt() -> None:
    assert compass_label(0) == "N"
    assert compass_label(45) == "NE"
    assert compass_label(90) == "L"
    assert compass_label(225) == "SO"


def test_angle_difference_wraps() -> None:
    assert angle_difference(350, 10) == 20
    assert angle_difference(10, 350) == 20
    assert angle_difference(0, 180) == 180


def test_polygon_area_of_a_small_square_at_the_equator() -> None:
    # At lat=0, cos(lat)=1, so both edges project to the exact same
    # km-per-degree — an easy case to hand-verify independently of the
    # function under test.
    side_deg = 0.01
    km_per_deg = math.radians(1.0) * EARTH_RADIUS_KM
    expected_side_km = side_deg * km_per_deg
    ring = [(0.0, 0.0), (0.0, side_deg), (side_deg, side_deg), (side_deg, 0.0)]

    area = polygon_area_km2(ring)

    assert abs(area - expected_side_km**2) < 1e-6


def test_polygon_area_ignores_ring_direction() -> None:
    ring_cw = [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01), (0.01, 0.0)]
    ring_ccw = list(reversed(ring_cw))
    assert polygon_area_km2(ring_cw) == polygon_area_km2(ring_ccw)


def test_polygon_area_of_a_degenerate_ring_is_zero() -> None:
    assert polygon_area_km2([]) == 0.0
    assert polygon_area_km2([(0.0, 0.0), (0.0, 0.01)]) == 0.0
