"""Comparação e validação de previsões — leitura/agregação (Fase 2, ADR-0082).

``get_model_comparison`` turns the rows ``workers.forecast_comparison_
pipeline`` accumulates into the metrics ``engine/validation.py`` defines —
MAE temperature, precipitation bias/MAE, wind MAE, rain-occurrence hit
rate, Brier score — per model, for one location. Never recommends a model
below ``settings.forecast_comparison_min_sample_size`` (see
``ModelMetrics.has_enough_samples``) — a critério de aceite explícito desta
fase.

Async/``AsyncSession``, called directly from the async HTTP router — same
convention as ``app.admin.service.get_validation_metrics`` — unlike the
two write-side jobs (``workers.forecast_comparison_pipeline``), which run
from sync Celery workers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.forecast_comparison.models import ForecastSnapshot
from engine.validation import (
    ForecastSample,
    PrecipitationErrorStats,
    brier_score,
    mean_absolute_temperature_error_c,
    mean_absolute_wind_error_kmh,
    precipitation_error,
    rain_occurrence_hit_rate,
)


@dataclass(frozen=True)
class ModelMetrics:
    model: str
    sample_count: int
    has_enough_samples: bool
    temperature_mae_c: float | None
    precipitation: PrecipitationErrorStats | None
    wind_mae_kmh: float | None
    rain_hit_rate: float | None
    brier_score: float | None


async def get_model_comparison(
    session: AsyncSession, *, location_id: uuid.UUID, settings: Settings | None = None
) -> list[ModelMetrics]:
    """Aggregate every fully-observed snapshot for one location into
    per-model metrics — read-only, no I/O beyond the query itself. A model
    with zero observed rows for this location simply doesn't appear (there
    is nothing yet to say about it), rather than showing as all-``None``.
    """
    settings = settings or get_settings()
    min_sample_size = settings.forecast_comparison_min_sample_size

    rows = list(
        (
            await session.execute(
                select(ForecastSnapshot).where(
                    ForecastSnapshot.location_id == location_id,
                    ForecastSnapshot.observed_at.is_not(None),
                )
            )
        ).scalars()
    )

    by_model: dict[str, list[ForecastSnapshot]] = {}
    for row in rows:
        by_model.setdefault(row.model, []).append(row)

    results: list[ModelMetrics] = []
    for model, model_rows in by_model.items():
        samples = [
            ForecastSample(
                provider=r.provider,
                model=r.model,
                location_id=str(r.location_id),
                horizon_hours=r.horizon_hours,
                temperature_predicted_c=r.temperature_max_predicted_c,
                temperature_observed_c=r.temperature_max_observed_c,
                rain_predicted_mm=r.precipitation_predicted_mm,
                rain_observed_mm=r.precipitation_observed_mm,
                rain_probability_percent=r.precipitation_probability_percent,
                wind_predicted_kmh=r.wind_gusts_predicted_kmh,
                wind_observed_kmh=r.wind_gusts_observed_kmh,
            )
            for r in model_rows
        ]
        results.append(
            ModelMetrics(
                model=model,
                sample_count=len(samples),
                has_enough_samples=len(samples) >= min_sample_size,
                temperature_mae_c=mean_absolute_temperature_error_c(samples),
                precipitation=precipitation_error(samples),
                wind_mae_kmh=mean_absolute_wind_error_kmh(samples),
                rain_hit_rate=rain_occurrence_hit_rate(samples),
                brier_score=brier_score(samples),
            )
        )
    return results
