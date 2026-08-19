"""Tests for the rule-based storm risk engine."""

from __future__ import annotations

from app.core.enums import RiskLevel, StormSeverity
from engine.risk.engine import RiskInput, StormRiskEngine


def test_far_weak_storm_is_green() -> None:
    engine = StormRiskEngine()
    result = engine.assess(
        RiskInput(distance_km=200, severity=StormSeverity.WEAK, eta_minutes=None)
    )
    assert result.severity is RiskLevel.GREEN
    assert result.score < 18
    assert result.experimental is True


def test_close_severe_storm_is_high() -> None:
    engine = StormRiskEngine()
    result = engine.assess(
        RiskInput(
            distance_km=8,
            severity=StormSeverity.SEVERE,
            max_reflectivity=60,
            speed_kmh=70,
            eta_minutes=10,
            is_mock=True,
        )
    )
    assert result.severity in (RiskLevel.ORANGE, RiskLevel.RED)
    assert result.score >= 40
    assert result.is_mock is True
    assert 0.0 <= result.rain_risk <= 1.0
    assert result.wind_risk > 0.5


def test_hail_requires_high_reflectivity() -> None:
    engine = StormRiskEngine()
    low = engine.assess(
        RiskInput(distance_km=10, severity=StormSeverity.SEVERE, max_reflectivity=30)
    )
    high = engine.assess(
        RiskInput(distance_km=10, severity=StormSeverity.SEVERE, max_reflectivity=60)
    )
    assert high.hail_risk > low.hail_risk
    assert high.hail_risk >= 0.9


def test_no_eta_means_zero_imminence_in_detail() -> None:
    engine = StormRiskEngine()
    result = engine.assess(
        RiskInput(distance_km=50, severity=StormSeverity.MODERATE, eta_minutes=None)
    )
    assert result.detail["imminence"] == 0.0
    assert result.eta_minutes is None


def test_all_risks_are_bounded() -> None:
    engine = StormRiskEngine()
    result = engine.assess(
        RiskInput(
            distance_km=0,
            severity=StormSeverity.SEVERE,
            max_reflectivity=99,
            speed_kmh=200,
            eta_minutes=0,
        )
    )
    for value in (result.rain_risk, result.wind_risk, result.hail_risk, result.lightning_risk):
        assert 0.0 <= value <= 1.0
    assert result.score <= 100.0
