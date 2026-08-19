"""Centralized, configurable thresholds — no magic numbers in the code.

These drive the alert levels (GREEN/YELLOW/ORANGE/RED). They live here as a
single source of truth and are consumed by the risk/alert engines in later
phases. Values are intentionally documented and overridable via settings so
they can be tuned without touching logic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.enums import RiskLevel


class RiskScoreThresholds(BaseModel):
    """Lower bounds (inclusive) of a 0–100 risk score for each level.

    A score >= red maps to RED, else >= orange maps to ORANGE, and so on.
    """

    yellow: float = Field(default=18.0, ge=0, le=100)
    orange: float = Field(default=40.0, ge=0, le=100)
    red: float = Field(default=65.0, ge=0, le=100)

    def classify(self, score: float) -> RiskLevel:
        if score >= self.red:
            return RiskLevel.RED
        if score >= self.orange:
            return RiskLevel.ORANGE
        if score >= self.yellow:
            return RiskLevel.YELLOW
        return RiskLevel.GREEN


class MonitoringDefaults(BaseModel):
    """Defaults applied to a monitored location when unspecified."""

    radius_km: float = Field(default=50.0, gt=0, le=500)


class AlertPolicy(BaseModel):
    """Anti-spam rules for the alert engine (FASE 9).

    An alert is (re)emitted only on a meaningful change: severity increase, ETA
    dropping by at least ``eta_change_minutes``, the storm getting at least
    ``distance_drop_km`` closer, or a new hazard appearing. Identical state never
    re-alerts (idempotency).
    """

    # Minimum level that warrants notifying the user at all.
    min_level: RiskLevel = RiskLevel.YELLOW
    # A hazard counts as "active" at/above this probability [0,1].
    hazard_active_threshold: float = Field(default=0.5, ge=0, le=1)
    # ETA must drop by at least this many minutes to re-alert.
    eta_change_minutes: int = Field(default=15, gt=0)
    # Storm must get at least this many km closer to re-alert.
    distance_drop_km: float = Field(default=10.0, gt=0)


class RiskConfig(BaseModel):
    """Aggregate risk/alert configuration."""

    score_thresholds: RiskScoreThresholds = Field(default_factory=RiskScoreThresholds)
    monitoring: MonitoringDefaults = Field(default_factory=MonitoringDefaults)
    alert_policy: AlertPolicy = Field(default_factory=AlertPolicy)
