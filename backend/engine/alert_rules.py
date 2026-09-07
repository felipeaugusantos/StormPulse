"""Custom alert rule evaluation (Fase 3 — Alertas Personalizados, ADR-0086).

Pure, side-effect-free functions — same "no I/O, testable against synthetic
data" approach as ``engine/validation.py``. ``app.alert_rules.service`` (or
the pipeline that calls this) is responsible for gathering the real
``MetricSnapshot`` from each location's actual forecast/current-conditions/
NDVI/lightning data and persisting whatever this decides.

**Condition model (DNF — disjunction of conjunctions):** a rule's
conditions are grouped by an integer ``group`` — every condition within the
same group must hold (AND); the rule matches if *any* group holds (OR).
This gives AND-of-conditions and OR-of-groups with a single flat list, no
separate "condition group" entity to manage, and matches how most
rule-builder UIs (Zapier-style "match ALL of / match ANY of") actually let
a user think about it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

Metric = Literal[
    "rain_mm",
    "rain_probability_percent",
    "wind_kmh",
    "temperature_c",
    "frost_temperature_c",
    "vpd_kpa",
    "soil_moisture_percent",
    "disease_risk_high",
    "lightning_distance_km",
    "storm_eta_minutes",
]

Operator = Literal[">", ">=", "<", "<=", "=="]

_OPERATORS: dict[Operator, Callable[[float, float], bool]] = {
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
    "==": lambda value, threshold: value == threshold,
}


@dataclass(frozen=True)
class MetricSnapshot:
    """Every metric a condition can reference, for one location at one
    evaluation moment. ``None`` means "unknown right now" (source disabled,
    provider unavailable, no talhão-level data) — a condition referencing a
    ``None`` metric never matches, it's never treated as 0 or False."""

    rain_mm: float | None = None
    rain_probability_percent: float | None = None
    wind_kmh: float | None = None
    temperature_c: float | None = None
    frost_temperature_c: float | None = None
    vpd_kpa: float | None = None
    soil_moisture_percent: float | None = None
    # 1.0 when engine.agro.classify_disease_risk says "high", else 0.0 —
    # kept numeric (not bool) so it composes with the same operator set as
    # every other metric (a condition of `disease_risk_high == 1` reads
    # naturally as "risk is high", `== 0` as "risk is not high").
    disease_risk_high: float | None = None
    lightning_distance_km: float | None = None
    # Minutes until the nearest tracked storm cell is expected to arrive —
    # "aproximação de tempestade" is expressed as this getting small
    # (`storm_eta_minutes <= 30`), not as a separate boolean.
    storm_eta_minutes: float | None = None

    def get(self, metric: Metric) -> float | None:
        value: float | None = getattr(self, metric)
        return value


@dataclass(frozen=True)
class AlertCondition:
    metric: Metric
    operator: Operator
    threshold: float
    group: int = 0


def evaluate_conditions(conditions: list[AlertCondition], snapshot: MetricSnapshot) -> bool:
    """DNF evaluation — see module docstring. An empty condition list never
    matches (a rule with no conditions is inert, not "always true") —
    that's a rule the UI should flag as incomplete, never one silently
    firing on everything."""
    return bool(matching_groups(conditions, snapshot))


def matching_groups(conditions: list[AlertCondition], snapshot: MetricSnapshot) -> list[int]:
    """Same DNF evaluation as `evaluate_conditions`, but returns *which*
    groups matched — used by the simulation endpoint to explain a result
    ("group 0 matched: wind > 40 AND rain > 10"), not just yes/no."""
    if not conditions:
        return []

    groups: dict[int, list[AlertCondition]] = {}
    for condition in conditions:
        groups.setdefault(condition.group, []).append(condition)

    return [
        group_index
        for group_index, group_conditions in groups.items()
        if _group_matches(group_conditions, snapshot)
    ]


def _group_matches(conditions: list[AlertCondition], snapshot: MetricSnapshot) -> bool:
    for condition in conditions:
        value = snapshot.get(condition.metric)
        if value is None:
            return False
        if not _OPERATORS[condition.operator](value, condition.threshold):
            return False
    return True


def is_within_quiet_hours(now: time, quiet_start: time | None, quiet_end: time | None) -> bool:
    """Whether `now` (local time) falls inside a configured quiet-hours
    window. Handles the window wrapping past midnight (e.g. 22:00–06:00) —
    a plain `start <= now < end` would be wrong for that case. No window
    configured (either bound `None`) means quiet hours are off."""
    if quiet_start is None or quiet_end is None:
        return False
    if quiet_start <= quiet_end:
        return quiet_start <= now < quiet_end
    return now >= quiet_start or now < quiet_end


def is_in_cooldown(last_fired_at: datetime | None, now: datetime, cooldown_minutes: int) -> bool:
    """Whether a rule that last fired at `last_fired_at` is still in its
    configured cooldown window. `cooldown_minutes <= 0` or never having
    fired before means no cooldown applies."""
    if last_fired_at is None or cooldown_minutes <= 0:
        return False
    return (now - last_fired_at) < timedelta(minutes=cooldown_minutes)
