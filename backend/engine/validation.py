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


# ---------------------------------------------------------------------------
# Fase 2 (Comparação e Validação de Previsões) — one (forecast, later
# observation) pair per numeric weather variable, per model, per location,
# per horizon. Same "pure function, no I/O, testable against synthetic data
# before real ground truth accumulates" approach as the ETA metrics above —
# ``app/forecast_comparison`` is the caller that turns real rows into these
# dataclasses and persists the aggregates.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastSample:
    """One forecast/observation pair for a single model, location and
    horizon. ``rain_predicted_mm``/``rain_observed_mm`` are ``None`` when the
    model or the ground-truth source doesn't carry that variable at all
    (never 0.0 standing in for "unknown") — every metric below skips a
    sample missing the field it needs, rather than treating a missing value
    as a zero.
    """

    provider: str
    model: str
    location_id: str
    horizon_hours: int
    temperature_predicted_c: float | None = None
    temperature_observed_c: float | None = None
    rain_predicted_mm: float | None = None
    rain_observed_mm: float | None = None
    rain_probability_percent: float | None = None
    wind_predicted_kmh: float | None = None
    wind_observed_kmh: float | None = None


def mean_absolute_temperature_error_c(samples: list[ForecastSample]) -> float | None:
    """MAE of predicted vs. observed temperature, in °C."""
    pairs = [
        (s.temperature_predicted_c, s.temperature_observed_c)
        for s in samples
        if s.temperature_predicted_c is not None and s.temperature_observed_c is not None
    ]
    if not pairs:
        return None
    return sum(abs(p - o) for p, o in pairs) / len(pairs)


@dataclass(frozen=True)
class PrecipitationErrorStats:
    """Bias (signed mean error — positive means the model over-forecasts
    rain) and MAE (unsigned) of predicted vs. observed precipitation, in mm.
    Both are needed: a model can have a small bias while still missing the
    amount badly on any given day (small bias, large MAE), or the reverse
    almost never happens but is not assumed away here.
    """

    bias_mm: float
    mae_mm: float
    sample_count: int


def precipitation_error(samples: list[ForecastSample]) -> PrecipitationErrorStats | None:
    pairs = [
        (s.rain_predicted_mm, s.rain_observed_mm)
        for s in samples
        if s.rain_predicted_mm is not None and s.rain_observed_mm is not None
    ]
    if not pairs:
        return None
    errors = [p - o for p, o in pairs]
    return PrecipitationErrorStats(
        bias_mm=sum(errors) / len(errors),
        mae_mm=sum(abs(e) for e in errors) / len(errors),
        sample_count=len(pairs),
    )


def mean_absolute_wind_error_kmh(samples: list[ForecastSample]) -> float | None:
    """MAE of predicted vs. observed wind speed, in km/h."""
    pairs = [
        (s.wind_predicted_kmh, s.wind_observed_kmh)
        for s in samples
        if s.wind_predicted_kmh is not None and s.wind_observed_kmh is not None
    ]
    if not pairs:
        return None
    return sum(abs(p - o) for p, o in pairs) / len(pairs)


# A day counts as "rained" at this threshold — matches the AGRO_DRY_SPELL_
# RAIN_THRESHOLD_MM default (app/core/config.py) so "did it rain" means the
# same thing across the codebase, not a second independent definition.
RAIN_OCCURRENCE_THRESHOLD_MM = 1.0


def rain_occurrence_hit_rate(samples: list[ForecastSample]) -> float | None:
    """Fraction of samples where the model's rain/no-rain call (predicted
    amount >= threshold) matched the observed rain/no-rain outcome —
    independent of how far off the *amount* was, which `precipitation_error`
    already covers.
    """
    pairs = [
        (s.rain_predicted_mm, s.rain_observed_mm)
        for s in samples
        if s.rain_predicted_mm is not None and s.rain_observed_mm is not None
    ]
    if not pairs:
        return None
    hits = sum(
        1
        for p, o in pairs
        if (p >= RAIN_OCCURRENCE_THRESHOLD_MM) == (o >= RAIN_OCCURRENCE_THRESHOLD_MM)
    )
    return hits / len(pairs)


def brier_score(samples: list[ForecastSample]) -> float | None:
    """Mean squared error between the forecast rain *probability* (0-1) and
    the observed binary outcome (1.0 rained, 0.0 didn't) — lower is better,
    0 is a perfect probabilistic forecast. Only meaningful for a model that
    actually issues a probability (``rain_probability_percent`` set); a
    model that only gives an amount has no probability to score here.
    """
    pairs = [
        (s.rain_probability_percent, s.rain_observed_mm)
        for s in samples
        if s.rain_probability_percent is not None and s.rain_observed_mm is not None
    ]
    if not pairs:
        return None
    total = 0.0
    for probability_percent, observed_mm in pairs:
        forecast_probability = probability_percent / 100
        outcome = 1.0 if observed_mm >= RAIN_OCCURRENCE_THRESHOLD_MM else 0.0
        total += (forecast_probability - outcome) ** 2
    return total / len(pairs)


# A recommendation ("model X is more reliable here") needs enough paired
# samples to not be noise — same spirit as MIN_SAMPLE_SIZE-style gates
# elsewhere in the codebase, just named for this context (ADR to follow in
# app/forecast_comparison once the accumulation job has run for a while).
MIN_SAMPLE_SIZE_FOR_RECOMMENDATION = 20


def has_minimum_sample_size(samples: list[ForecastSample]) -> bool:
    return len(samples) >= MIN_SAMPLE_SIZE_FOR_RECOMMENDATION
