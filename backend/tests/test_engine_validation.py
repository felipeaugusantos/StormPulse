"""Tests for engine/validation.py — synthetic prediction/observation data,
since no real ground truth exists yet (hardening ADR-0036)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.validation import (
    DataLatencySample,
    EtaSample,
    PredictionOutcome,
    ProviderAttempt,
    mean_absolute_eta_error_minutes,
    mean_data_latency_seconds_by_provider,
    precision_recall,
    precision_recall_by_event_type,
    provider_availability,
)


def test_precision_recall_perfect_predictions() -> None:
    outcomes = [
        PredictionOutcome("hail", predicted=True, observed=True),
        PredictionOutcome("hail", predicted=False, observed=False),
    ]
    result = precision_recall(outcomes)
    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 0
    assert result.true_negatives == 1
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_precision_recall_with_false_positives_and_negatives() -> None:
    outcomes = [
        PredictionOutcome("hail", predicted=True, observed=True),  # TP
        PredictionOutcome("hail", predicted=True, observed=False),  # FP
        PredictionOutcome("hail", predicted=False, observed=True),  # FN
        PredictionOutcome("hail", predicted=False, observed=False),  # TN
    ]
    result = precision_recall(outcomes)
    assert result.true_positives == 1
    assert result.false_positives == 1
    assert result.false_negatives == 1
    assert result.true_negatives == 1
    assert result.precision == 0.5
    assert result.recall == 0.5


def test_precision_recall_returns_none_not_zero_when_no_positive_predictions() -> None:
    outcomes = [PredictionOutcome("hail", predicted=False, observed=False)]
    result = precision_recall(outcomes)
    assert result.precision is None  # 0/0, not misleadingly 0.0
    assert result.recall is None


def test_precision_recall_by_event_type_keeps_types_separate() -> None:
    outcomes = [
        PredictionOutcome("hail", predicted=True, observed=True),
        PredictionOutcome("hail", predicted=True, observed=True),
        PredictionOutcome("lightning", predicted=True, observed=False),
    ]
    result = precision_recall_by_event_type(outcomes)
    assert result["hail"].precision == 1.0
    assert result["lightning"].precision == 0.0
    # Hail's perfect record must not be diluted by lightning's failure.
    assert result["hail"].true_positives == 2


def test_eta_error_sign_reflects_direction() -> None:
    predicted = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    late = EtaSample(predicted_arrival=predicted, actual_arrival=predicted + timedelta(minutes=10))
    early = EtaSample(predicted_arrival=predicted, actual_arrival=predicted - timedelta(minutes=5))
    assert late.error_minutes == 10.0
    assert early.error_minutes == -5.0


def test_mean_absolute_eta_error_ignores_direction() -> None:
    predicted = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    samples = [
        EtaSample(predicted, predicted + timedelta(minutes=10)),
        EtaSample(predicted, predicted - timedelta(minutes=10)),
    ]
    # +10 and -10 must average to 10 (absolute), not 0.
    assert mean_absolute_eta_error_minutes(samples) == 10.0


def test_mean_absolute_eta_error_empty_is_none_not_zero() -> None:
    assert mean_absolute_eta_error_minutes([]) is None


def test_mean_data_latency_by_provider() -> None:
    now = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    samples = [
        DataLatencySample("inmet", now - timedelta(minutes=10), now),
        DataLatencySample("inmet", now - timedelta(minutes=20), now),
        DataLatencySample("cptec", now - timedelta(minutes=30), now),
    ]
    result = mean_data_latency_seconds_by_provider(samples)
    assert result["inmet"] == 15 * 60  # mean of 10min and 20min
    assert result["cptec"] == 30 * 60


def test_provider_availability_fraction_succeeded() -> None:
    attempts = [
        ProviderAttempt("inmet", succeeded=True),
        ProviderAttempt("inmet", succeeded=True),
        ProviderAttempt("inmet", succeeded=False),
        ProviderAttempt("cptec", succeeded=True),
    ]
    result = provider_availability(attempts)
    assert result["inmet"] == 2 / 3
    assert result["cptec"] == 1.0
