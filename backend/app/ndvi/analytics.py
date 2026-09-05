"""Pure historical analytics for vegetation indices.

No value is inferred from a missing/cloud-obscured acquisition. Every
calculation receives only persisted observations and explicitly filters to
reliable ones before building a baseline or detecting a persistent fall.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from itertools import pairwise

from app.core.enums import ImageQuality

MINIMUM_ANOMALY_HISTORY = 5
PERSISTENT_DROP_POINTS = 3
PERSISTENT_DROP_MIN_ABSOLUTE = 0.08


def quality_from_valid_pixels(valid_pixel_percent: float) -> ImageQuality:
    if valid_pixel_percent >= 80:
        return ImageQuality.HIGH
    if valid_pixel_percent >= 60:
        return ImageQuality.MEDIUM
    return ImageQuality.LOW


@dataclass(frozen=True)
class HistoricalValue:
    value: float
    reliable: bool


@dataclass(frozen=True)
class AnomalyResult:
    baseline_count: int
    baseline_mean: float | None
    difference: float | None
    percent_difference: float | None
    z_score: float | None
    status: str


def calculate_anomaly(
    current: HistoricalValue | None,
    history: list[HistoricalValue],
    *,
    minimum_history: int = MINIMUM_ANOMALY_HISTORY,
) -> AnomalyResult:
    baseline = [item.value for item in history if item.reliable]
    if current is None or not current.reliable or len(baseline) < minimum_history:
        return AnomalyResult(len(baseline), None, None, None, None, "insufficient_history")

    mean = statistics.fmean(baseline)
    difference = current.value - mean
    percent = difference / abs(mean) * 100 if mean != 0 else None
    deviation = statistics.pstdev(baseline)
    z_score = difference / deviation if deviation > 0 else None
    if (z_score is not None and z_score <= -2) or (percent is not None and percent <= -20):
        status = "below_expected"
    elif (z_score is not None and z_score >= 2) or (percent is not None and percent >= 20):
        status = "above_expected"
    else:
        status = "normal"
    return AnomalyResult(
        len(baseline),
        round(mean, 4),
        round(difference, 4),
        round(percent, 1) if percent is not None else None,
        round(z_score, 2) if z_score is not None else None,
        status,
    )


def has_persistent_drop(
    values: list[HistoricalValue],
    *,
    required_points: int = PERSISTENT_DROP_POINTS,
    minimum_absolute_drop: float = PERSISTENT_DROP_MIN_ABSOLUTE,
) -> bool:
    reliable = [item.value for item in values if item.reliable]
    if len(reliable) < required_points:
        return False
    recent = reliable[-required_points:]
    return all(current < previous for previous, current in pairwise(recent)) and (
        recent[0] - recent[-1] >= minimum_absolute_drop
    )
