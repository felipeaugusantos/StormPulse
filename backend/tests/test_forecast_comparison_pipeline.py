"""Tests for workers/forecast_comparison_pipeline.py (Fase 2, ADR-0082).

Needs a real Postgres — same pattern as ``test_agro_pipeline.py``: tenant/
user/location built directly in the sync session and rolled back at the
end. A small fake implementing ``MultiModelForecastProvider`` stands in for
Open-Meteo so this exercises only the decision logic, not any real network
shape (that's ``test_weather_open_meteo.py``'s job).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import blind_index
from app.forecast_comparison.models import ForecastSnapshot
from app.locations.models import Location
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.open_meteo import ModelDailyPoint, ObservedDailyPoint
from app.weather.provider import WeatherProviderUnavailableError
from workers.db import session_scope
from workers.forecast_comparison_pipeline import (
    HORIZON_BUCKETS_HOURS,
    _snapshot_one_location,
    fill_observed_values,
    record_forecast_snapshots,
)

pytestmark = pytest.mark.integration

_MODELS = ["ecmwf_ifs025", "gfs_seamless"]


class _FakeMultiModelProvider:
    def __init__(
        self,
        forecasts: dict[str, list[ModelDailyPoint]] | None = None,
        observations: list[ObservedDailyPoint] | None = None,
        raise_on_forecast: bool = False,
        fail_first_n_forecast_calls: int = 0,
    ) -> None:
        self._forecasts = forecasts or {}
        self._observations = observations or []
        self._raise_on_forecast = raise_on_forecast
        self._fail_first_n_forecast_calls = fail_first_n_forecast_calls
        self.forecast_calls = 0
        self.observation_calls = 0

    async def get_multi_model_forecast(
        self, latitude: float, longitude: float, *, models: list[str], forecast_days: int = 7
    ) -> dict[str, list[ModelDailyPoint]]:
        self.forecast_calls += 1
        if self._raise_on_forecast or self.forecast_calls <= self._fail_first_n_forecast_calls:
            raise WeatherProviderUnavailableError("simulated failure")
        return self._forecasts

    async def get_daily_observations(
        self, latitude: float, longitude: float, *, start_date: date, end_date: date
    ) -> list[ObservedDailyPoint]:
        self.observation_calls += 1
        return self._observations


def _make_location(session: Session) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"forecast-cmp-{unique}@example.com"
    user = User(
        tenant_id=tenant.id,
        email=email,
        email_index=blind_index(email),
        hashed_password="not-a-real-hash",
        is_active=True,
    )
    session.add(user)
    session.flush()
    location = Location(
        tenant_id=tenant.id,
        user_id=user.id,
        name="Talhão (teste)",
        kind="farm",
        latitude=-21.1775,
        longitude=-47.8103,
        radius_km=10,
        is_active=True,
    )
    session.add(location)
    session.flush()
    return location


def _forecasts_for_every_horizon(now: datetime) -> dict[str, list[ModelDailyPoint]]:
    days = [(now + timedelta(hours=h)).date() for h in HORIZON_BUCKETS_HOURS]
    return {
        model: [
            ModelDailyPoint(
                day=day,
                model=model,
                temperature_max_c=30.0,
                precipitation_mm=5.0,
                precipitation_probability_percent=40.0,
                wind_gusts_max_kmh=20.0,
            )
            for day in days
        ]
        for model in _MODELS
    }


def test_record_forecast_snapshots_disabled_returns_early() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", forecast_comparison_enabled=False)
        summary = record_forecast_snapshots(
            session, settings=settings, provider=_FakeMultiModelProvider()
        )
        assert summary.enabled is False
        session.rollback()


def test_record_forecast_snapshots_creates_one_row_per_model_and_horizon() -> None:
    with session_scope() as session:
        location = _make_location(session)
        now = datetime.now(UTC)
        settings = Settings(
            environment="test",
            forecast_comparison_enabled=True,
            forecast_comparison_models=",".join(_MODELS),
        )
        provider = _FakeMultiModelProvider(forecasts=_forecasts_for_every_horizon(now))

        # Scoped to this test's own location only — the shared dev DB may
        # carry other real active locations (same caveat as
        # test_agro_pipeline.py), so the aggregate summary count isn't
        # asserted on here.
        record_forecast_snapshots(session, settings=settings, provider=provider)

        rows = session.scalars(
            select(ForecastSnapshot).where(ForecastSnapshot.location_id == location.id)
        ).all()
        assert len(rows) == len(_MODELS) * len(HORIZON_BUCKETS_HOURS)
        assert {r.model for r in rows} == set(_MODELS)
        assert {r.horizon_hours for r in rows} == set(HORIZON_BUCKETS_HOURS)
        assert all(r.temperature_max_predicted_c == 30.0 for r in rows)
        session.rollback()


def test_record_forecast_snapshots_upserts_instead_of_duplicating() -> None:
    with session_scope() as session:
        location = _make_location(session)
        now = datetime.now(UTC)
        settings = Settings(
            environment="test",
            forecast_comparison_enabled=True,
            forecast_comparison_models=",".join(_MODELS),
        )
        provider = _FakeMultiModelProvider(forecasts=_forecasts_for_every_horizon(now))

        record_forecast_snapshots(session, settings=settings, provider=provider)
        record_forecast_snapshots(session, settings=settings, provider=provider)

        rows = session.scalars(
            select(ForecastSnapshot).where(ForecastSnapshot.location_id == location.id)
        ).all()
        assert len(rows) == len(_MODELS) * len(HORIZON_BUCKETS_HOURS)
        session.rollback()


def test_one_location_failing_does_not_stop_the_others() -> None:
    """Exercises the per-location unit directly (``_snapshot_one_location``)
    rather than the full ``record_forecast_snapshots`` cycle — the shared
    dev DB used by these integration tests may carry other real active
    locations (same caveat as ``test_agro_pipeline.py``), so asserting on
    aggregate counts across *every* location in the database would be
    unreliable. This isolates exactly the behavior being tested: one
    location's provider call raising must not prevent another location's
    call, made with a fresh provider, from succeeding."""
    with session_scope() as session:
        failing_location = _make_location(session)
        working_location = _make_location(session)
        now = datetime.now(UTC)

        failing_provider = _FakeMultiModelProvider(raise_on_forecast=True)
        recorded_for_failing = _snapshot_one_location(
            session, failing_location, failing_provider, models=_MODELS, now=now
        )

        working_provider = _FakeMultiModelProvider(forecasts=_forecasts_for_every_horizon(now))
        recorded_for_working = _snapshot_one_location(
            session, working_location, working_provider, models=_MODELS, now=now
        )

        assert recorded_for_failing == 0
        assert recorded_for_working == len(_MODELS) * len(HORIZON_BUCKETS_HOURS)
        assert (
            session.scalars(
                select(ForecastSnapshot).where(ForecastSnapshot.location_id == failing_location.id)
            ).all()
            == []
        )
        assert len(
            session.scalars(
                select(ForecastSnapshot).where(ForecastSnapshot.location_id == working_location.id)
            ).all()
        ) == len(_MODELS) * len(HORIZON_BUCKETS_HOURS)
        session.rollback()


def test_fill_observed_values_fills_pending_past_snapshots() -> None:
    with session_scope() as session:
        location = _make_location(session)
        past_date = datetime.now(UTC).date() - timedelta(days=2)
        snapshot = ForecastSnapshot(
            tenant_id=location.tenant_id,
            location_id=location.id,
            provider="Open-Meteo",
            model="ecmwf_ifs025",
            target_date=past_date,
            horizon_hours=24,
            snapshot_taken_at=datetime.now(UTC) - timedelta(days=3),
            temperature_max_predicted_c=28.0,
            precipitation_predicted_mm=2.0,
        )
        session.add(snapshot)
        session.flush()

        settings = Settings(environment="test", forecast_comparison_enabled=True)
        provider = _FakeMultiModelProvider(
            observations=[
                ObservedDailyPoint(
                    day=past_date,
                    temperature_max_c=29.5,
                    precipitation_mm=1.0,
                    wind_gusts_max_kmh=18.0,
                )
            ]
        )

        summary = fill_observed_values(session, settings=settings, provider=provider)

        assert summary.observations_filled == 1
        session.flush()
        session.refresh(snapshot)
        assert snapshot.observed_at is not None
        assert snapshot.temperature_max_observed_c == 29.5
        assert snapshot.precipitation_observed_mm == 1.0
        session.rollback()


def test_fill_observed_values_ignores_snapshots_whose_target_date_has_not_happened_yet() -> None:
    with session_scope() as session:
        location = _make_location(session)
        future_date = datetime.now(UTC).date() + timedelta(days=3)
        snapshot = ForecastSnapshot(
            tenant_id=location.tenant_id,
            location_id=location.id,
            provider="Open-Meteo",
            model="ecmwf_ifs025",
            target_date=future_date,
            horizon_hours=72,
            snapshot_taken_at=datetime.now(UTC),
        )
        session.add(snapshot)
        session.flush()

        settings = Settings(environment="test", forecast_comparison_enabled=True)
        provider = _FakeMultiModelProvider()

        # Scoped to this test's own snapshot only — the shared dev DB may
        # carry other real pending (past-due) snapshots, so
        # `provider.observation_calls` isn't asserted on globally here.
        fill_observed_values(session, settings=settings, provider=provider)

        session.refresh(snapshot)
        assert snapshot.observed_at is None
        session.rollback()


# `get_model_comparison` itself (async/AsyncSession, aggregation math) is
# covered end-to-end via the HTTP endpoint in
# test_integration_forecast_comparison.py — same split as
# app.admin.service.get_validation_metrics/test_admin_validation.py: rows
# seeded here with the sync session, the read path exercised through the
# real async router.
