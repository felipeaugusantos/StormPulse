"""Comparação e validação de previsões — pipeline de coleta (Fase 2, ADR-0082).

Two independent periodic jobs, mirroring ``workers/agro_pipeline.py``'s
structure (own decision logic, per-location error isolation — a provider
failure for one location never stops the others):

- ``record_forecast_snapshots`` — once a day, asks Open-Meteo for
  ECMWF/GFS/ICON side by side and stores what each model predicted for a
  small fixed set of horizons (24h/72h/120h ahead), per active location.
- ``fill_observed_values`` — once a day, finds snapshots whose
  ``target_date`` has already passed and fills in what actually happened,
  from the same archive/ERA5 endpoint already trusted elsewhere in this
  codebase for historical rainfall (see ``ObservedDailyPoint``).

The read side (turning accumulated rows into metrics for the HTTP API) is
``app.forecast_comparison.service.get_model_comparison`` — same split as
``workers/deforestation_pipeline.py`` (write/cycle) vs.
``app.deforestation.*`` (domain model/provider/read).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.forecast_comparison.models import ForecastSnapshot
from app.locations.models import Location
from app.weather.factory import get_forecast_comparison_provider
from app.weather.open_meteo import ModelDailyPoint, ObservedDailyPoint
from app.weather.provider import WeatherProviderUnavailableError

logger = logging.getLogger(__name__)


class MultiModelForecastProvider(Protocol):
    """Structural type for the two ``OpenMeteoWeatherProvider`` methods this
    module needs — lets tests substitute a lightweight fake without
    subclassing the concrete Open-Meteo client (same spirit as
    ``app.weather.provider.WeatherProvider`` for the single-model
    interface, just scoped to Fase 2's two extra methods)."""

    async def get_multi_model_forecast(
        self, latitude: float, longitude: float, *, models: list[str], forecast_days: int = 7
    ) -> dict[str, list[ModelDailyPoint]]: ...

    async def get_daily_observations(
        self, latitude: float, longitude: float, *, start_date: date, end_date: date
    ) -> list[ObservedDailyPoint]: ...


_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)

# Fixed, small horizon set — "performance by horizon" means the same three
# buckets everywhere, not an arbitrary hour count that happened to fall out
# of when the daily job ran. Day-granularity: Open-Meteo's daily forecast
# has no sub-day resolution to compare against anyway.
HORIZON_BUCKETS_HOURS: tuple[int, ...] = (24, 72, 120)

_PROVIDER_NAME = "Open-Meteo"


@dataclass
class ForecastComparisonCycleSummary:
    enabled: bool
    locations_checked: int = 0
    snapshots_recorded: int = 0
    observations_filled: int = 0


def _target_date_for_horizon(collected_on: datetime, horizon_hours: int) -> date:
    return (collected_on + timedelta(hours=horizon_hours)).date()


def _snapshot_one_location(
    session: Session,
    location: Location,
    provider: MultiModelForecastProvider,
    *,
    models: list[str],
    now: datetime,
) -> int:
    """One location's worth of ``record_forecast_snapshots`` — split out so
    a failure here (caught by the caller) never touches any other
    location's processing, and so this is independently testable without a
    real ``Location`` query. Returns how many snapshot rows were
    written/updated."""
    max_horizon_days = max(HORIZON_BUCKETS_HOURS) // 24 + 1
    try:
        forecasts = asyncio.run(
            provider.get_multi_model_forecast(
                location.latitude,
                location.longitude,
                models=models,
                forecast_days=max_horizon_days,
            )
        )
    except _RECOVERABLE as exc:
        logger.warning(
            "forecast_comparison: multi-model forecast unavailable for location %s (%s)",
            location.id,
            exc,
        )
        return 0

    snapshots_recorded = 0
    for horizon_hours in HORIZON_BUCKETS_HOURS:
        target_date = _target_date_for_horizon(now, horizon_hours)
        for model in models:
            points = forecasts.get(model, [])
            point = next((p for p in points if p.day == target_date), None)
            if point is None:
                continue

            existing = session.scalars(
                select(ForecastSnapshot).where(
                    ForecastSnapshot.location_id == location.id,
                    ForecastSnapshot.provider == _PROVIDER_NAME,
                    ForecastSnapshot.model == model,
                    ForecastSnapshot.target_date == target_date,
                    ForecastSnapshot.horizon_hours == horizon_hours,
                )
            ).first()
            if existing is None:
                existing = ForecastSnapshot(
                    tenant_id=location.tenant_id,
                    location_id=location.id,
                    provider=_PROVIDER_NAME,
                    model=model,
                    target_date=target_date,
                    horizon_hours=horizon_hours,
                )
                session.add(existing)
            existing.snapshot_taken_at = now
            existing.temperature_max_predicted_c = point.temperature_max_c
            existing.precipitation_predicted_mm = point.precipitation_mm
            existing.precipitation_probability_percent = point.precipitation_probability_percent
            existing.wind_gusts_predicted_kmh = point.wind_gusts_max_kmh
            snapshots_recorded += 1
    return snapshots_recorded


def record_forecast_snapshots(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: MultiModelForecastProvider | None = None,
) -> ForecastComparisonCycleSummary:
    """Daily job: one multi-model call per active location, one snapshot row
    per (model, horizon bucket) — upserted, so re-running the same day just
    refreshes ``snapshot_taken_at``/the predicted values instead of
    duplicating rows (the unique constraint would reject a duplicate
    anyway). A failure for one location (``_snapshot_one_location``'s own
    try/except) never stops the others."""
    settings = settings or get_settings()
    if not settings.forecast_comparison_enabled:
        return ForecastComparisonCycleSummary(enabled=False)

    provider = provider or get_forecast_comparison_provider(settings)
    if provider is None:
        return ForecastComparisonCycleSummary(enabled=False)

    models = settings.forecast_comparison_models_list
    locations = list(session.scalars(select(Location).where(Location.is_active.is_(True))))
    now = datetime.now(UTC)

    snapshots_recorded = sum(
        _snapshot_one_location(session, location, provider, models=models, now=now)
        for location in locations
    )

    return ForecastComparisonCycleSummary(
        enabled=True,
        locations_checked=len(locations),
        snapshots_recorded=snapshots_recorded,
    )


def fill_observed_values(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: MultiModelForecastProvider | None = None,
) -> ForecastComparisonCycleSummary:
    """Daily job: for every snapshot whose ``target_date`` is already in the
    past and still has no observation, fetch the real archive/ERA5 value and
    fill it in. Grouped per location so each location needs only one
    archive call covering every pending date for it, not one call per row.
    """
    settings = settings or get_settings()
    if not settings.forecast_comparison_enabled:
        return ForecastComparisonCycleSummary(enabled=False)

    provider = provider or get_forecast_comparison_provider(settings)
    if provider is None:
        return ForecastComparisonCycleSummary(enabled=False)

    today = datetime.now(UTC).date()
    pending = list(
        session.scalars(
            select(ForecastSnapshot).where(
                ForecastSnapshot.target_date < today,
                ForecastSnapshot.observed_at.is_(None),
            )
        )
    )
    if not pending:
        return ForecastComparisonCycleSummary(enabled=True)

    by_location: dict[uuid.UUID, list[ForecastSnapshot]] = {}
    for row in pending:
        by_location.setdefault(row.location_id, []).append(row)

    now = datetime.now(UTC)
    filled = 0
    for location_id, rows in by_location.items():
        location = session.get(Location, location_id)
        if location is None:
            continue  # deleted since the snapshot was taken.

        start_date = min(r.target_date for r in rows)
        end_date = max(r.target_date for r in rows)
        try:
            observations = asyncio.run(
                provider.get_daily_observations(
                    location.latitude, location.longitude, start_date=start_date, end_date=end_date
                )
            )
        except _RECOVERABLE as exc:
            logger.warning(
                "forecast_comparison: observations unavailable for location %s (%s)",
                location_id,
                exc,
            )
            continue

        by_day = {o.day: o for o in observations}
        for row in rows:
            observed = by_day.get(row.target_date)
            if observed is None:
                continue
            row.observed_at = now
            row.temperature_max_observed_c = observed.temperature_max_c
            row.precipitation_observed_mm = observed.precipitation_mm
            row.wind_gusts_observed_kmh = observed.wind_gusts_max_kmh
            filled += 1

    return ForecastComparisonCycleSummary(enabled=True, observations_filled=filled)
