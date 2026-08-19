"""StormRiskEngine (FASE 8) — rule-based, documented, no false intelligence.

Combines a storm cell's intensity with its distance and trajectory (speed, ETA)
to a monitored location, producing per-hazard risks and an aggregate level.

⚠️ EXPERIMENTAL and possibly MOCK: every heuristic here is an explicit,
documented rule over the inputs — NOT a validated meteorological model, and NOT
supercell identification (ADR-0005). Outputs carry ``experimental``/``is_mock``
so consumers never mistake them for real, verified forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import RiskLevel, StormSeverity
from app.core.thresholds import RiskScoreThresholds
from engine.config import DEFAULT_RISK, RiskConfig


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class RiskInput:
    """Processed inputs for one (storm, location) pair."""

    distance_km: float
    severity: StormSeverity
    max_reflectivity: float | None = None
    speed_kmh: float | None = None
    eta_minutes: int | None = None
    is_mock: bool = False


@dataclass(frozen=True)
class RiskAssessment:
    """Materializable risk result (mirrors the StormRisk model / API contract)."""

    severity: RiskLevel
    score: float
    rain_risk: float
    wind_risk: float
    hail_risk: float
    lightning_risk: float
    storm_distance_km: float | None
    storm_speed_kmh: float | None
    eta_minutes: int | None
    is_mock: bool
    experimental: bool = True
    detail: dict[str, Any] = field(default_factory=dict)


class StormRiskEngine:
    """Deterministic, rule-based risk assessment."""

    def __init__(
        self,
        config: RiskConfig = DEFAULT_RISK,
        thresholds: RiskScoreThresholds | None = None,
    ) -> None:
        self.config = config
        self.thresholds = thresholds or RiskScoreThresholds()

    def _intensity(self, severity: StormSeverity) -> float:
        c = self.config
        return {
            StormSeverity.WEAK: c.intensity_weak,
            StormSeverity.MODERATE: c.intensity_moderate,
            StormSeverity.STRONG: c.intensity_strong,
            StormSeverity.SEVERE: c.intensity_severe,
        }[severity]

    def assess(self, data: RiskInput) -> RiskAssessment:
        c = self.config
        intensity = self._intensity(data.severity)

        closeness = _clamp01(1.0 - data.distance_km / c.reference_range_km)
        imminence = (
            0.0
            if data.eta_minutes is None
            else _clamp01(1.0 - data.eta_minutes / c.eta_horizon_min)
        )

        wind_speed_factor = (
            0.0 if data.speed_kmh is None else _clamp01(data.speed_kmh / c.wind_speed_ref_kmh)
        )
        hail_base = (
            0.0
            if data.max_reflectivity is None
            else _clamp01(data.max_reflectivity / c.hail_reflectivity_dbz)
        )

        rain_risk = _clamp01(intensity * (0.5 + 0.5 * closeness))
        wind_risk = _clamp01(intensity * (0.4 + 0.6 * wind_speed_factor))
        hail_risk = _clamp01(intensity * hail_base)
        lightning_risk = _clamp01(intensity * (0.6 + 0.4 * closeness))

        hazard_component = max(rain_risk, wind_risk, hail_risk, lightning_risk)
        score = 100.0 * _clamp01(
            c.weight_hazard * hazard_component
            + c.weight_proximity * closeness
            + c.weight_imminence * imminence
        )
        level = self.thresholds.classify(score)

        return RiskAssessment(
            severity=level,
            score=round(score, 1),
            rain_risk=round(rain_risk, 2),
            wind_risk=round(wind_risk, 2),
            hail_risk=round(hail_risk, 2),
            lightning_risk=round(lightning_risk, 2),
            storm_distance_km=round(data.distance_km, 2),
            storm_speed_kmh=data.speed_kmh,
            eta_minutes=data.eta_minutes,
            is_mock=data.is_mock,
            experimental=True,
            detail={
                "intensity": round(intensity, 2),
                "closeness": round(closeness, 2),
                "imminence": round(imminence, 2),
                "rule": "weighted-max-hazard-v1",
            },
        )
