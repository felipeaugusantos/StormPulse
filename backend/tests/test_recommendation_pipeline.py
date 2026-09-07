"""Integration tests for workers/recommendation_pipeline.py (Fase 5,
ADR-0089).

Needs a real Postgres — same pattern as ``test_alert_rules_pipeline.py``:
tenant/user/location built directly in the sync session. A deterministic
fake ``WeatherProvider`` stands in for Open-Meteo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import blind_index
from app.core.enums import AlertEventType, RiskLevel
from app.core.enums import WeatherSourceKind as _WSK
from app.locations.models import Location
from app.recommendations.models import RecommendedAction
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    ForecastPoint,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
)
from workers.db import session_scope
from workers.recommendation_pipeline import run_recommendation_cycle

pytestmark = pytest.mark.integration


class _FakeProvider(WeatherProvider):
    """Deterministic stand-in — a fixed value for wind/temperature/rain
    "today"."""

    def __init__(
        self,
        *,
        wind_kmh: float = 5.0,
        temperature_min_c: float = 15.0,
        rain_probability: int = 10,
    ) -> None:
        self._wind_kmh = wind_kmh
        self._temperature_min_c = temperature_min_c
        self._rain_probability = rain_probability

    @property
    def name(self) -> str:
        return "FAKE"

    @property
    def kind(self) -> _WSK:
        return _WSK.FORECAST_MODEL

    def _provenance(self) -> Provenance:
        return Provenance(source_name=self.name, source_kind=self.kind, is_mock=False)

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=datetime.now(UTC),
            latitude=latitude,
            longitude=longitude,
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        return []

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        return []

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        today = datetime.now(UTC)
        return Forecast(
            provenance=self._provenance(),
            latitude=latitude,
            longitude=longitude,
            points=[
                ForecastPoint(
                    time=today,
                    temperature_mean_c=20.0,
                    temperature_min_c=self._temperature_min_c,
                    wind_gusts_max_kmh=self._wind_kmh,
                    humidity_mean_percent=50.0,
                    precipitation_mm=0.0,
                    precipitation_probability=self._rain_probability,
                )
            ],
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        return RainfallHistory(
            provenance=self._provenance(), latitude=latitude, longitude=longitude, daily=[]
        )


def _make_tenant_user_location(session: Session) -> tuple[Tenant, User, Location]:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"recommendations-{unique}@example.com"
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
    return tenant, user, location


def test_frost_recommendation_created_when_temperature_is_severe() -> None:
    with session_scope() as session:
        _, _, location = _make_tenant_user_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider(temperature_min_c=1.0)

        summary = run_recommendation_cycle(session, settings=settings, provider=provider)

        assert summary.recommendations_created >= 1
        action = session.scalars(
            select(RecommendedAction).where(
                RecommendedAction.location_id == location.id,
                RecommendedAction.rule_key == "frost_severe_irrigation",
            )
        ).one()
        assert action.level == RiskLevel.RED
        assert "irrigação" in action.message


def test_no_recommendation_when_no_rule_matches() -> None:
    with session_scope() as session:
        _, _, location = _make_tenant_user_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider(temperature_min_c=15.0, wind_kmh=5.0, rain_probability=5)

        summary = run_recommendation_cycle(session, settings=settings, provider=provider)

        assert summary.recommendations_created == 0
        actions = session.scalars(
            select(RecommendedAction).where(RecommendedAction.location_id == location.id)
        ).all()
        assert actions == []


def test_same_rule_is_not_duplicated_within_the_same_day() -> None:
    with session_scope() as session:
        _, _, location = _make_tenant_user_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider(temperature_min_c=1.0)

        first = run_recommendation_cycle(session, settings=settings, provider=provider)
        second = run_recommendation_cycle(session, settings=settings, provider=provider)

        assert first.recommendations_created >= 1
        assert second.recommendations_created == 0
        assert second.recommendations_skipped_duplicate >= 1
        actions = session.scalars(
            select(RecommendedAction).where(
                RecommendedAction.location_id == location.id,
                RecommendedAction.rule_key == "frost_severe_irrigation",
            )
        ).all()
        assert len(actions) == 1


def test_recommendation_links_to_a_same_day_frost_warning_alert_when_one_exists() -> None:
    from app.alerts.models import Alert

    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        alert = Alert(
            tenant_id=tenant.id,
            user_id=user.id,
            location_id=location.id,
            event_type=AlertEventType.FROST_WARNING,
            level=RiskLevel.RED,
            title="Geada severa prevista",
            message="Temperatura mínima abaixo de 3°C.",
            dedup_key=f"{location.id}:{uuid.uuid4().hex}:frost_warning",
        )
        session.add(alert)
        session.flush()
        settings = Settings(environment="test")
        provider = _FakeProvider(temperature_min_c=1.0)

        run_recommendation_cycle(session, settings=settings, provider=provider)

        action = session.scalars(
            select(RecommendedAction).where(
                RecommendedAction.location_id == location.id,
                RecommendedAction.rule_key == "frost_severe_irrigation",
            )
        ).one()
        assert action.alert_id == alert.id


def test_a_location_can_get_more_than_one_recommendation_in_the_same_cycle() -> None:
    with session_scope() as session:
        _, _, location = _make_tenant_user_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider(temperature_min_c=1.0, wind_kmh=50.0, rain_probability=70)

        run_recommendation_cycle(session, settings=settings, provider=provider)

        rule_keys = {
            a.rule_key
            for a in session.scalars(
                select(RecommendedAction).where(RecommendedAction.location_id == location.id)
            ).all()
        }
        assert rule_keys == {"frost_severe_irrigation", "wind_rain_delay_spray"}
