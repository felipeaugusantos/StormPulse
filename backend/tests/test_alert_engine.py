"""Tests for the alert engine: idempotency and anti-spam rules."""

from __future__ import annotations

from app.alerts.engine import AlertEngine, is_suppressed_by_preference, snapshot
from app.core.enums import AlertEventType, AlertType, RiskLevel
from app.core.thresholds import AlertPolicy
from engine.risk.engine import RiskAssessment

POLICY = AlertPolicy()
LOC = "loc-1"
CELL = "cell-1"


def _risk(
    level: RiskLevel,
    *,
    eta: int | None = 30,
    distance: float | None = 40.0,
    rain: float = 0.6,
    wind: float = 0.6,
    hail: float = 0.0,
    lightning: float = 0.6,
) -> RiskAssessment:
    return RiskAssessment(
        severity=level,
        score=50.0,
        rain_risk=rain,
        wind_risk=wind,
        hail_risk=hail,
        lightning_risk=lightning,
        storm_distance_km=distance,
        storm_speed_kmh=40.0,
        eta_minutes=eta,
        is_mock=True,
    )


def test_first_actionable_alert_emits() -> None:
    engine = AlertEngine(POLICY)
    decision = engine.decide(_risk(RiskLevel.ORANGE), None, location_id=LOC, storm_cell_id=CELL)
    assert decision.emit is True
    assert decision.event_type is AlertEventType.STORM_APPROACHING
    assert decision.dedup_key is not None


def test_below_threshold_does_not_emit() -> None:
    engine = AlertEngine(POLICY)
    decision = engine.decide(_risk(RiskLevel.GREEN), None, location_id=LOC, storm_cell_id=CELL)
    assert decision.emit is False


def test_identical_state_is_idempotent() -> None:
    engine = AlertEngine(POLICY)
    current = _risk(RiskLevel.ORANGE)
    prev = snapshot(current, POLICY)
    decision = engine.decide(current, prev, location_id=LOC, storm_cell_id=CELL)
    assert decision.emit is False
    assert "no meaningful change" in decision.reasons


def test_escalation_emits_intensified() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.YELLOW), POLICY)
    decision = engine.decide(_risk(RiskLevel.ORANGE), prev, location_id=LOC, storm_cell_id=CELL)
    assert decision.emit is True
    assert decision.event_type is AlertEventType.STORM_INTENSIFIED


def test_eta_drop_emits_approaching() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.ORANGE, eta=50), POLICY)
    decision = engine.decide(
        _risk(RiskLevel.ORANGE, eta=20), prev, location_id=LOC, storm_cell_id=CELL
    )
    assert decision.emit is True
    assert decision.event_type is AlertEventType.STORM_APPROACHING


def test_small_eta_change_is_suppressed() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.ORANGE, eta=50), POLICY)
    decision = engine.decide(
        _risk(RiskLevel.ORANGE, eta=45), prev, location_id=LOC, storm_cell_id=CELL
    )
    assert decision.emit is False


def test_getting_closer_emits() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.ORANGE, distance=40, eta=30), POLICY)
    decision = engine.decide(
        _risk(RiskLevel.ORANGE, distance=20, eta=30), prev, location_id=LOC, storm_cell_id=CELL
    )
    assert decision.emit is True
    assert decision.event_type is AlertEventType.STORM_APPROACHING


def test_new_hazard_emits_risk_changed() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.ORANGE, hail=0.0), POLICY)
    decision = engine.decide(
        _risk(RiskLevel.ORANGE, hail=0.8), prev, location_id=LOC, storm_cell_id=CELL
    )
    assert decision.emit is True
    assert decision.event_type is AlertEventType.STORM_RISK_CHANGED
    assert "hail" in decision.active_hazards


def test_storm_passed_emits_once() -> None:
    engine = AlertEngine(POLICY)
    prev = snapshot(_risk(RiskLevel.ORANGE), POLICY)
    passed = engine.decide(_risk(RiskLevel.GREEN), prev, location_id=LOC, storm_cell_id=CELL)
    assert passed.emit is True
    assert passed.event_type is AlertEventType.STORM_PASSED
    # Once green is the previous state too, no further alerts.
    green_prev = snapshot(_risk(RiskLevel.GREEN), POLICY)
    again = engine.decide(_risk(RiskLevel.GREEN), green_prev, location_id=LOC, storm_cell_id=CELL)
    assert again.emit is False


def test_dedup_key_stable_for_same_state() -> None:
    engine = AlertEngine(POLICY)
    a = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    b = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert a.dedup_key == b.dedup_key


# --- is_suppressed_by_preference (item "AlertPreference é um recurso morto") ---


def test_disabling_severe_storm_suppresses_everything() -> None:
    engine = AlertEngine(POLICY)
    decision = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert is_suppressed_by_preference(decision, frozenset({AlertType.SEVERE_STORM})) is True


def test_no_disabled_types_never_suppresses() -> None:
    engine = AlertEngine(POLICY)
    decision = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert is_suppressed_by_preference(decision, frozenset()) is False


def test_disabling_severe_cell_suppresses_only_first_contact_events() -> None:
    engine = AlertEngine(POLICY)
    # First alert for a (location, storm) pair is always STORM_APPROACHING,
    # not a first-contact event — SEVERE_CELL must not touch it.
    decision = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert decision.event_type is AlertEventType.STORM_APPROACHING
    assert is_suppressed_by_preference(decision, frozenset({AlertType.SEVERE_CELL})) is False


def test_disabling_the_only_active_hazard_suppresses() -> None:
    engine = AlertEngine(POLICY)
    only_hail = _risk(RiskLevel.RED, rain=0.0, wind=0.0, hail=0.8, lightning=0.0)
    decision = engine.decide(only_hail, None, location_id=LOC, storm_cell_id=CELL)
    assert decision.active_hazards == frozenset({"hail"})
    assert is_suppressed_by_preference(decision, frozenset({AlertType.HAIL})) is True


def test_disabling_an_unrelated_hazard_does_not_suppress() -> None:
    engine = AlertEngine(POLICY)
    only_hail = _risk(RiskLevel.RED, rain=0.0, wind=0.0, hail=0.8, lightning=0.0)
    decision = engine.decide(only_hail, None, location_id=LOC, storm_cell_id=CELL)
    # Only "hail" is active on this decision — disabling LIGHTNING alone
    # (a hazard that isn't active here at all) must not suppress it.
    assert is_suppressed_by_preference(decision, frozenset({AlertType.LIGHTNING})) is False


def test_disabling_all_active_hazards_suppresses() -> None:
    engine = AlertEngine(POLICY)
    # Default _risk() has rain/wind/lightning active (>=0.5), hail inactive.
    decision = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert decision.active_hazards == frozenset({"rain", "wind", "lightning"})
    all_but_hail = frozenset({AlertType.RAIN_INTENSE, AlertType.STRONG_WIND, AlertType.LIGHTNING})
    assert is_suppressed_by_preference(decision, all_but_hail) is True


def test_disabling_only_some_active_hazards_does_not_suppress() -> None:
    engine = AlertEngine(POLICY)
    decision = engine.decide(_risk(RiskLevel.RED), None, location_id=LOC, storm_cell_id=CELL)
    assert is_suppressed_by_preference(decision, frozenset({AlertType.RAIN_INTENSE})) is False
