"""Tests for engine/recommendations.py — the deterministic risk→action
catalog (Fase 5, ADR-0089). Each rule is tested for both its matching and
non-matching case; the multi-match case confirms no rule "wins" over
another."""

from __future__ import annotations

from engine.alert_rules import MetricSnapshot
from engine.recommendations import RULES, evaluate_recommendations


def test_frost_rule_matches_severe_cold_and_not_mild_cold() -> None:
    cold = MetricSnapshot(frost_temperature_c=1.0)
    mild = MetricSnapshot(frost_temperature_c=6.0)
    assert any(r.key == "frost_severe_irrigation" for r in evaluate_recommendations(cold))
    assert not any(r.key == "frost_severe_irrigation" for r in evaluate_recommendations(mild))


def test_frost_rule_never_matches_when_temperature_is_unknown() -> None:
    assert evaluate_recommendations(MetricSnapshot()) == []


def test_wind_rain_rule_needs_both_conditions_together() -> None:
    both = MetricSnapshot(wind_kmh=50.0, rain_probability_percent=70.0)
    wind_only = MetricSnapshot(wind_kmh=50.0, rain_probability_percent=10.0)
    rain_only = MetricSnapshot(wind_kmh=10.0, rain_probability_percent=70.0)
    assert any(r.key == "wind_rain_delay_spray" for r in evaluate_recommendations(both))
    assert not any(r.key == "wind_rain_delay_spray" for r in evaluate_recommendations(wind_only))
    assert not any(r.key == "wind_rain_delay_spray" for r in evaluate_recommendations(rain_only))


def test_water_stress_rule_needs_both_dry_soil_and_high_vpd() -> None:
    both = MetricSnapshot(soil_moisture_percent=15.0, vpd_kpa=2.0)
    dry_only = MetricSnapshot(soil_moisture_percent=15.0, vpd_kpa=0.5)
    assert any(r.key == "water_stress_irrigation" for r in evaluate_recommendations(both))
    assert not any(r.key == "water_stress_irrigation" for r in evaluate_recommendations(dry_only))


def test_a_location_can_trigger_more_than_one_recommendation() -> None:
    snapshot = MetricSnapshot(frost_temperature_c=1.0, wind_kmh=50.0, rain_probability_percent=70.0)
    matched_keys = {r.key for r in evaluate_recommendations(snapshot)}
    assert matched_keys == {"frost_severe_irrigation", "wind_rain_delay_spray"}


def test_every_rule_key_is_unique() -> None:
    keys = [r.key for r in RULES]
    assert len(keys) == len(set(keys))
