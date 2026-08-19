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


class RiskConfig(BaseModel):
    """Aggregate risk/alert configuration."""

    score_thresholds: RiskScoreThresholds = Field(default_factory=RiskScoreThresholds)
    monitoring: MonitoringDefaults = Field(default_factory=MonitoringDefaults)
