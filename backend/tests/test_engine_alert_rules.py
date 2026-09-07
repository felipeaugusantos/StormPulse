"""Tests for engine/alert_rules.py — condition evaluation (AND/OR), quiet
hours and cooldown (Fase 3, ADR-0086). Quiet hours and encerramento
(cooldown/closing) are explicit acceptance criteria for this phase."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from engine.alert_rules import (
    AlertCondition,
    MetricSnapshot,
    evaluate_conditions,
    is_in_cooldown,
    is_within_quiet_hours,
)


def test_empty_conditions_never_match() -> None:
    assert evaluate_conditions([], MetricSnapshot(wind_kmh=100.0)) is False


def test_single_condition_matches_when_threshold_crossed() -> None:
    conditions = [AlertCondition(metric="wind_kmh", operator=">", threshold=40.0)]
    assert evaluate_conditions(conditions, MetricSnapshot(wind_kmh=41.0)) is True
    assert evaluate_conditions(conditions, MetricSnapshot(wind_kmh=40.0)) is False


def test_conditions_in_the_same_group_are_anded() -> None:
    conditions = [
        AlertCondition(metric="wind_kmh", operator=">", threshold=40.0, group=0),
        AlertCondition(metric="rain_probability_percent", operator=">=", threshold=70.0, group=0),
    ]
    both = MetricSnapshot(wind_kmh=45.0, rain_probability_percent=80.0)
    only_wind = MetricSnapshot(wind_kmh=45.0, rain_probability_percent=20.0)
    assert evaluate_conditions(conditions, both) is True
    assert evaluate_conditions(conditions, only_wind) is False


def test_conditions_in_different_groups_are_ored() -> None:
    conditions = [
        AlertCondition(metric="frost_temperature_c", operator="<=", threshold=3.0, group=0),
        AlertCondition(metric="wind_kmh", operator=">", threshold=60.0, group=1),
    ]
    only_frost = MetricSnapshot(frost_temperature_c=1.0, wind_kmh=10.0)
    only_wind = MetricSnapshot(frost_temperature_c=15.0, wind_kmh=70.0)
    neither = MetricSnapshot(frost_temperature_c=15.0, wind_kmh=10.0)
    assert evaluate_conditions(conditions, only_frost) is True
    assert evaluate_conditions(conditions, only_wind) is True
    assert evaluate_conditions(conditions, neither) is False


def test_a_missing_metric_never_matches_never_treated_as_zero() -> None:
    conditions = [AlertCondition(metric="soil_moisture_percent", operator="<", threshold=20.0)]
    assert evaluate_conditions(conditions, MetricSnapshot(soil_moisture_percent=None)) is False


def test_storm_approach_reads_as_eta_getting_small() -> None:
    conditions = [AlertCondition(metric="storm_eta_minutes", operator="<=", threshold=30.0)]
    assert evaluate_conditions(conditions, MetricSnapshot(storm_eta_minutes=15.0)) is True
    assert evaluate_conditions(conditions, MetricSnapshot(storm_eta_minutes=120.0)) is False


# ---------------------------------------------------------------------------
# Horário silencioso
# ---------------------------------------------------------------------------


def test_quiet_hours_disabled_when_no_window_configured() -> None:
    assert is_within_quiet_hours(time(23, 0), None, None) is False


def test_quiet_hours_same_day_window() -> None:
    start, end = time(12, 0), time(14, 0)
    assert is_within_quiet_hours(time(13, 0), start, end) is True
    assert is_within_quiet_hours(time(11, 59), start, end) is False
    assert is_within_quiet_hours(time(14, 0), start, end) is False  # end is exclusive


def test_quiet_hours_window_wraps_past_midnight() -> None:
    start, end = time(22, 0), time(6, 0)
    assert is_within_quiet_hours(time(23, 30), start, end) is True
    assert is_within_quiet_hours(time(3, 0), start, end) is True
    assert is_within_quiet_hours(time(12, 0), start, end) is False


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


def test_cooldown_never_applies_without_a_previous_fire() -> None:
    assert is_in_cooldown(None, datetime.now(UTC), cooldown_minutes=30) is False


def test_cooldown_zero_or_negative_means_disabled() -> None:
    now = datetime.now(UTC)
    assert is_in_cooldown(now - timedelta(minutes=1), now, cooldown_minutes=0) is False
    assert is_in_cooldown(now - timedelta(minutes=1), now, cooldown_minutes=-5) is False


def test_cooldown_blocks_within_the_window_and_releases_after() -> None:
    now = datetime.now(UTC)
    fired_5_min_ago = now - timedelta(minutes=5)
    assert is_in_cooldown(fired_5_min_ago, now, cooldown_minutes=30) is True
    fired_31_min_ago = now - timedelta(minutes=31)
    assert is_in_cooldown(fired_31_min_ago, now, cooldown_minutes=30) is False
