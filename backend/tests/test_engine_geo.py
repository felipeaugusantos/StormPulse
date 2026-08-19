"""Tests for great-circle geometry helpers."""

from __future__ import annotations

from engine.geo import (
    angle_difference,
    bearing_deg,
    compass_label,
    destination_point,
    haversine_km,
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
