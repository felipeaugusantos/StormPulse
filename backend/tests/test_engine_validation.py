"""Tests for engine/validation.py — synthetic prediction/observation data,
since no real ground truth exists yet (hardening ADR-0036)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.validation import (
    DataLatencySample,
    EtaSample,
    ForecastSample,
    PredictionOutcome,
    ProviderAttempt,
    brier_score,
    has_minimum_sample_size,
    mean_absolute_eta_error_minutes,
    mean_absolute_temperature_error_c,
    mean_absolute_wind_error_kmh,
    mean_data_latency_seconds_by_provider,
    precipitation_error,
    precision_recall,
    precision_recall_by_event_type,
    provider_availability,
    rain_occurrence_hit_rate,
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


# ---------------------------------------------------------------------------
# Fase 2 — comparação e validação de previsões
# ---------------------------------------------------------------------------


def _forecast_sample(**overrides: object) -> ForecastSample:
    base: dict[str, object] = {
        "provider": "open_meteo",
        "model": "ecmwf_ifs025",
        "location_id": "loc-1",
        "horizon_hours": 24,
    }
    base.update(overrides)
    return ForecastSample(**base)  # type: ignore[arg-type]


def test_mean_absolute_temperature_error_ignores_direction() -> None:
    samples = [
        _forecast_sample(temperature_predicted_c=30.0, temperature_observed_c=32.0),
        _forecast_sample(temperature_predicted_c=25.0, temperature_observed_c=23.0),
    ]
    assert mean_absolute_temperature_error_c(samples) == 2.0


def test_mean_absolute_temperature_error_skips_samples_missing_either_side() -> None:
    samples = [
        _forecast_sample(temperature_predicted_c=30.0, temperature_observed_c=None),
        _forecast_sample(temperature_predicted_c=None, temperature_observed_c=32.0),
    ]
    assert mean_absolute_temperature_error_c(samples) is None


def test_mean_absolute_temperature_error_empty_is_none_not_zero() -> None:
    assert mean_absolute_temperature_error_c([]) is None


def test_precipitation_error_bias_reflects_over_forecasting() -> None:
    samples = [
        _forecast_sample(rain_predicted_mm=20.0, rain_observed_mm=10.0),
        _forecast_sample(rain_predicted_mm=10.0, rain_observed_mm=10.0),
    ]
    result = precipitation_error(samples)
    assert result is not None
    assert result.bias_mm == 5.0  # (+10, 0) averaged
    assert result.mae_mm == 5.0
    assert result.sample_count == 2


def test_precipitation_error_bias_can_be_negative_for_under_forecasting() -> None:
    samples = [_forecast_sample(rain_predicted_mm=5.0, rain_observed_mm=15.0)]
    result = precipitation_error(samples)
    assert result is not None
    assert result.bias_mm == -10.0
    assert result.mae_mm == 10.0


def test_precipitation_error_none_when_no_paired_samples() -> None:
    assert precipitation_error([_forecast_sample()]) is None


def test_mean_absolute_wind_error() -> None:
    samples = [
        _forecast_sample(wind_predicted_kmh=20.0, wind_observed_kmh=25.0),
        _forecast_sample(wind_predicted_kmh=10.0, wind_observed_kmh=8.0),
    ]
    assert mean_absolute_wind_error_kmh(samples) == 3.5


def test_rain_occurrence_hit_rate_counts_matching_yes_no_calls() -> None:
    samples = [
        _forecast_sample(rain_predicted_mm=5.0, rain_observed_mm=3.0),  # both "rained"
        _forecast_sample(rain_predicted_mm=0.0, rain_observed_mm=0.0),  # both "dry"
        _forecast_sample(rain_predicted_mm=5.0, rain_observed_mm=0.0),  # miss
        _forecast_sample(rain_predicted_mm=0.0, rain_observed_mm=5.0),  # miss
    ]
    assert rain_occurrence_hit_rate(samples) == 0.5


def test_rain_occurrence_hit_rate_none_without_paired_samples() -> None:
    assert rain_occurrence_hit_rate([]) is None


def test_brier_score_zero_for_perfect_probabilistic_forecasts() -> None:
    samples = [
        _forecast_sample(rain_probability_percent=100.0, rain_observed_mm=5.0),
        _forecast_sample(rain_probability_percent=0.0, rain_observed_mm=0.0),
    ]
    assert brier_score(samples) == 0.0


def test_brier_score_penalizes_confident_wrong_forecasts() -> None:
    # 100% confident it would rain, but it didn't: (1.0 - 0.0)^2 = 1.0.
    samples = [_forecast_sample(rain_probability_percent=100.0, rain_observed_mm=0.0)]
    assert brier_score(samples) == 1.0


def test_brier_score_none_without_probability_forecasts() -> None:
    samples = [_forecast_sample(rain_predicted_mm=5.0, rain_observed_mm=5.0)]
    assert brier_score(samples) is None


def test_has_minimum_sample_size() -> None:
    small = [_forecast_sample() for _ in range(5)]
    enough = [_forecast_sample() for _ in range(20)]
    assert has_minimum_sample_size(small) is False
    assert has_minimum_sample_size(enough) is True
