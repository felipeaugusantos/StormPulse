"""Deterministic risk→action recommendation catalog (Fase 5, ADR-0089).

Pure, side-effect-free functions — same "no I/O, testable against synthetic
data" approach as `engine/alert_rules.py`, and reuses its exact condition
model (`MetricSnapshot`, `AlertCondition`, DNF evaluation via `group`):
a recommendation rule is just an `AlertCondition` list plus the text to show
when it matches. `workers/recommendation_pipeline.py` gathers the real
`MetricSnapshot` and persists whatever this decides.

Deliberately small (3 rules), each using only metrics already computed
elsewhere in the system — never a fabricated signal, never an LLM deciding
the action (an LLM may only rephrase an already-decided recommendation's
text, same rule as `StormRiskEngine`/`AlertEngine`, ADR-0005/0060). See
ADR-0089 for why the roadmap's own original examples ("colheita pendente",
"cultura sensível") aren't implementable yet — they'd need data the system
doesn't collect.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import AlertEventType, RiskLevel
from engine.alert_rules import AlertCondition, MetricSnapshot, matching_groups


@dataclass(frozen=True)
class RecommendationRule:
    key: str
    title: str
    message: str
    level: RiskLevel
    conditions: list[AlertCondition]
    # When a matching `Alert` of this event type exists for the same
    # location/day, the recommendation links to it (`RecommendedAction.
    # alert_id`) — never required for the rule to fire, just extra context
    # when it's available.
    related_alert_event_type: AlertEventType | None = None


RULES: tuple[RecommendationRule, ...] = (
    RecommendationRule(
        key="frost_severe_irrigation",
        title="Geada severa prevista",
        message=(
            "Risco de geada severa nas próximas horas — considere irrigação "
            "por aspersão ou cobertura das plantas."
        ),
        level=RiskLevel.RED,
        conditions=[AlertCondition(metric="frost_temperature_c", operator="<=", threshold=3.0)],
        related_alert_event_type=AlertEventType.FROST_WARNING,
    ),
    RecommendationRule(
        key="wind_rain_delay_spray",
        title="Vento forte e chuva prevista",
        message="Vento forte e chuva prevista — considere adiar a pulverização.",
        level=RiskLevel.ORANGE,
        conditions=[
            AlertCondition(metric="wind_kmh", operator=">", threshold=40.0, group=0),
            AlertCondition(
                metric="rain_probability_percent", operator=">=", threshold=60.0, group=0
            ),
        ],
    ),
    RecommendationRule(
        key="water_stress_irrigation",
        title="Estresse hídrico",
        message=("Solo seco e alta demanda evaporativa — considere irrigação."),
        level=RiskLevel.ORANGE,
        conditions=[
            AlertCondition(metric="soil_moisture_percent", operator="<", threshold=30.0, group=0),
            AlertCondition(metric="vpd_kpa", operator=">", threshold=1.6, group=0),
        ],
        related_alert_event_type=AlertEventType.DRY_SPELL_WARNING,
    ),
)


def evaluate_recommendations(snapshot: MetricSnapshot) -> list[RecommendationRule]:
    """Every rule in `RULES` whose conditions match `snapshot`, in catalog
    order. A location can trigger more than one — never picks a single
    "winner", each is its own independent recommendation."""
    return [rule for rule in RULES if matching_groups(rule.conditions, snapshot)]
