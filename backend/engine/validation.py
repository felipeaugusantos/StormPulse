"""Forecast/detection validation infrastructure (hardening ADR-0036).

Pure, side-effect-free functions for computing accuracy metrics from
prediction/observation pairs — false positive/negative, precision/recall by
event type, ETA error, and per-provider data latency/availability. Nothing
here computes a weather classification or changes any threshold; it only
*measures* how the existing classification did against a later real
outcome.

Building this now — before any real ground-truth observation exists in the
database (``AlertVerification`` is new, unpopulated infrastructure, see
``app/alerts/verification_models.py``) — establishes the exact input format
predictions/observations must be recorded in, and lets the metrics
themselves be verified against synthetic data immediately, independent of
when real ground truth starts accumulating. See ADR-0036 for why the system
is not yet classified as appropriate for safety-critical alerting: these
functions have nothing to compute real numbers from yet.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PredictionOutcome:
    """One (prediction, later-observed-reality) pair for a single event type."""

    event_type: str
    predicted: bool
    observed: bool


@dataclass(frozen=True)
class ConfusionCounts:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    # `None` (not 0.0) when the denominator is 0 — "no positive predictions
    # were made" is a different, honest statement from "precision is 0%".
    precision: float | None
    recall: float | None


def precision_recall(outcomes: list[PredictionOutcome]) -> ConfusionCounts:
    """Aggregate precision/recall across all given outcomes (any event type)."""
    tp = sum(1 for o in outcomes if o.predicted and o.observed)
    fp = sum(1 for o in outcomes if o.predicted and not o.observed)
    fn = sum(1 for o in outcomes if not o.predicted and o.observed)
    tn = sum(1 for o in outcomes if not o.predicted and not o.observed)
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    return ConfusionCounts(tp, fp, fn, tn, precision, recall)


def precision_recall_by_event_type(
    outcomes: list[PredictionOutcome],
) -> dict[str, ConfusionCounts]:
    """Same as ``precision_recall``, grouped by ``event_type`` — a single
    aggregate number would hide a type (e.g. hail) performing much worse
    than another (e.g. rain), which matters more for deciding trust per
    alert kind than one blended figure.
    """
    grouped: dict[str, list[PredictionOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.event_type].append(outcome)
    return {event_type: precision_recall(group) for event_type, group in grouped.items()}


@dataclass(frozen=True)
class EtaSample:
    """One ETA prediction and what actually happened."""

    predicted_arrival: datetime
    actual_arrival: datetime

    @property
    def error_minutes(self) -> float:
        """Positive: arrived later than predicted. Negative: arrived earlier."""
        return (self.actual_arrival - self.predicted_arrival).total_seconds() / 60


def mean_absolute_eta_error_minutes(samples: list[EtaSample]) -> float | None:
    """Mean absolute error, in minutes — direction-agnostic (an ETA that's
    10 minutes early is treated the same as one 10 minutes late). Returns
    `None` for an empty sample set rather than a misleading 0.0.
    """
    if not samples:
        return None
    return sum(abs(s.error_minutes) for s in samples) / len(samples)


@dataclass(frozen=True)
class DataLatencySample:
    """How stale a piece of weather data was at the moment it was used —
    same underlying event ``app.core.metrics.record_weather_data_age``
    records live; this is the batch/offline equivalent for historical
    analysis.
    """

    provider: str
    observed_at: datetime
    used_at: datetime

    @property
    def latency_seconds(self) -> float:
        return (self.used_at - self.observed_at).total_seconds()


def mean_data_latency_seconds_by_provider(
    samples: list[DataLatencySample],
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        grouped[sample.provider].append(sample.latency_seconds)
    return {provider: sum(values) / len(values) for provider, values in grouped.items()}


@dataclass(frozen=True)
class ProviderAttempt:
    """One call to a weather provider — whether it was the primary or had
    to fall back, and whether it ultimately succeeded at all (both
    providers can fail, see ``app.weather.fallback.FallbackWeatherProvider``).
    """

    provider: str
    succeeded: bool


def provider_availability(attempts: list[ProviderAttempt]) -> dict[str, float]:
    """Fraction of attempts that succeeded, per provider — a direct
    aggregate of ``stormpulse.weather.source_used``
    (``app/core/metrics.py``) over some time window, for historical
    reporting rather than the live metric.
    """
    grouped: dict[str, list[bool]] = defaultdict(list)
    for attempt in attempts:
        grouped[attempt.provider].append(attempt.succeeded)
    return {
        provider: sum(1 for ok in results if ok) / len(results)
        for provider, results in grouped.items()
    }
