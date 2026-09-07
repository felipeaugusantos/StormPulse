"""Tests for engine/agro.py — VPD and disease-risk math ported from the
frontend (web/src/agro.ts) for Fase 3's backend rule engine."""

from __future__ import annotations

import pytest

from engine.agro import classify_disease_risk, classify_vpd, vapor_pressure_deficit_kpa


def test_vpd_decreases_as_humidity_rises_at_a_fixed_temperature() -> None:
    dry = vapor_pressure_deficit_kpa(25.0, 30.0)
    humid = vapor_pressure_deficit_kpa(25.0, 90.0)
    assert humid < dry


def test_vpd_known_value_matches_the_tetens_formula() -> None:
    # svp = 0.6108 * e^(17.27*25/(25+237.3)) ≈ 3.1674 kPa
    # vpd = svp * (1 - 0.5) ≈ 1.5837 kPa
    assert vapor_pressure_deficit_kpa(25.0, 50.0) == pytest.approx(1.5837, abs=1e-3)


def test_classify_vpd_boundaries() -> None:
    assert classify_vpd(0.39) == "low"
    assert classify_vpd(0.4) == "ideal"
    assert classify_vpd(1.6) == "ideal"
    assert classify_vpd(1.61) == "high"


def test_disease_risk_high_needs_both_humid_and_mild_temperature() -> None:
    thresholds = {"humidity_threshold_percent": 80.0, "min_temp_c": 15.0, "max_temp_c": 30.0}
    assert classify_disease_risk(85.0, 22.0, **thresholds) == "high"
    assert classify_disease_risk(50.0, 22.0, **thresholds) == "low"  # dry, mild temp
    assert classify_disease_risk(85.0, 35.0, **thresholds) == "low"  # humid, too hot


def test_disease_risk_unknown_when_data_missing() -> None:
    thresholds = {"humidity_threshold_percent": 80.0, "min_temp_c": 15.0, "max_temp_c": 30.0}
    assert classify_disease_risk(None, 22.0, **thresholds) == "unknown"
    assert classify_disease_risk(85.0, None, **thresholds) == "unknown"
