"""Alert engine (FASE 9) — event-driven, idempotent, anti-spam.

Pure decision logic: given the current risk for a (user, location) and the
snapshot of the last alert, decide whether to (re)notify, which event it is, and
a stable ``dedup_key`` that makes repeated identical state a no-op (idempotency).
Persistence and delivery live in the worker/notification layers (FASE 10+).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import AlertEventType, RiskLevel
from app.core.thresholds import AlertPolicy
from engine.risk.engine import RiskAssessment

# Explicit ordering for the levels (StrEnum has no natural order).
_LEVEL_RANK: dict[RiskLevel, int] = {
    RiskLevel.GREEN: 0,
    RiskLevel.YELLOW: 1,
    RiskLevel.ORANGE: 2,
    RiskLevel.RED: 3,
}

_HAZARD_FIELDS = ("rain_risk", "wind_risk", "hail_risk", "lightning_risk")


@dataclass(frozen=True)
class AlertState:
    """Snapshot of the last alert emitted for a (location, storm) pair."""

    level: RiskLevel
    eta_minutes: int | None
    distance_km: float | None
    active_hazards: frozenset[str]


@dataclass(frozen=True)
class AlertDecision:
    emit: bool
    event_type: AlertEventType | None
    level: RiskLevel
    active_hazards: frozenset[str]
    reasons: list[str] = field(default_factory=list)
    dedup_key: str | None = None


def active_hazards(assessment: RiskAssessment, policy: AlertPolicy) -> frozenset[str]:
    """Names of hazards at/above the policy's activity threshold."""
    return frozenset(
        name.removesuffix("_risk")
        for name in _HAZARD_FIELDS
        if getattr(assessment, name) >= policy.hazard_active_threshold
    )


def snapshot(assessment: RiskAssessment, policy: AlertPolicy) -> AlertState:
    """Build the persistable state from an assessment (for the next comparison)."""
    return AlertState(
        level=assessment.severity,
        eta_minutes=assessment.eta_minutes,
        distance_km=assessment.storm_distance_km,
        active_hazards=active_hazards(assessment, policy),
    )


class AlertEngine:
    """Decides whether an assessment warrants a (new) alert."""

    def __init__(self, policy: AlertPolicy | None = None) -> None:
        self.policy = policy or AlertPolicy()

    def decide(
        self,
        current: RiskAssessment,
        previous: AlertState | None,
        *,
        location_id: str,
        storm_cell_id: str | None,
    ) -> AlertDecision:
        policy = self.policy
        hazards = active_hazards(current, policy)
        level = current.severity
        min_rank = _LEVEL_RANK[policy.min_level]

        # Below the actionable threshold.
        if _LEVEL_RANK[level] < min_rank:
            if previous is not None and _LEVEL_RANK[previous.level] >= min_rank:
                return self._decision(
                    True,
                    AlertEventType.STORM_PASSED,
                    level,
                    hazards,
                    ["storm no longer meets alert threshold"],
                    location_id,
                    storm_cell_id,
                )
            return AlertDecision(False, None, level, hazards, ["below alert threshold"])

        # First actionable alert for this pair.
        if previous is None:
            return self._decision(
                True,
                AlertEventType.STORM_APPROACHING,
                level,
                hazards,
                ["first alert for this storm"],
                location_id,
                storm_cell_id,
            )

        reasons: list[str] = []
        event: AlertEventType | None = None

        if _LEVEL_RANK[level] > _LEVEL_RANK[previous.level]:
            event = AlertEventType.STORM_INTENSIFIED
            reasons.append(f"severity rose {previous.level.value}→{level.value}")

        new_hazards = hazards - previous.active_hazards
        if new_hazards:
            event = event or AlertEventType.STORM_RISK_CHANGED
            reasons.append(f"new hazard(s): {', '.join(sorted(new_hazards))}")

        if self._eta_dropped(previous.eta_minutes, current.eta_minutes):
            event = event or AlertEventType.STORM_APPROACHING
            reasons.append("ETA dropped significantly")

        if self._got_closer(previous.distance_km, current.storm_distance_km):
            event = event or AlertEventType.STORM_APPROACHING
            reasons.append("storm got significantly closer")

        if event is None:
            return AlertDecision(False, None, level, hazards, ["no meaningful change"])

        return self._decision(True, event, level, hazards, reasons, location_id, storm_cell_id)

    def _eta_dropped(self, prev: int | None, curr: int | None) -> bool:
        if curr is None:
            return False
        if prev is None:
            return True  # newly-known ETA is meaningful
        return (prev - curr) >= self.policy.eta_change_minutes

    def _got_closer(self, prev: float | None, curr: float | None) -> bool:
        if curr is None or prev is None:
            return False
        return (prev - curr) >= self.policy.distance_drop_km

    def _decision(
        self,
        emit: bool,
        event: AlertEventType,
        level: RiskLevel,
        hazards: frozenset[str],
        reasons: list[str],
        location_id: str,
        storm_cell_id: str | None,
    ) -> AlertDecision:
        return AlertDecision(
            emit=emit,
            event_type=event,
            level=level,
            active_hazards=hazards,
            reasons=reasons,
            dedup_key=self._dedup_key(event, level, location_id, storm_cell_id),
        )

    def _dedup_key(
        self,
        event: AlertEventType,
        level: RiskLevel,
        location_id: str,
        storm_cell_id: str | None,
    ) -> str:
        """Stable key: identical (pair, event, level) never re-alerts."""
        return f"{location_id}:{storm_cell_id or '-'}:{event.value}:{level.value}"
