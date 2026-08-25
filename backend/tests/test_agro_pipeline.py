"""Tests for the agronomic advisory pipeline (FASE 19).

``dry_streak_days`` is pure (no I/O) and unit-tested directly. The alert-
emission path (``run_agro_advisory_cycle``) needs a real Postgres — same
pattern as ``test_integration_satellite.py``: tenant/user/location built
directly in the sync session and rolled back at the end, never committed,
so repeated runs never pollute the shared dev database. A small fake
``WeatherProvider`` stands in for INMET/CPTEC so this exercises only the
decision logic, not any real network shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings
from app.core.crypto import blind_index
from app.core.enums import AlertEventType, RiskLevel, WeatherSourceKind
from app.locations.models import Location
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.provider import (
    CurrentConditions,
    DailyRainfall,
    Forecast,
    ForecastPoint,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
)
from workers.agro_pipeline import classify_frost_days, dry_streak_days, run_agro_advisory_cycle
from workers.db import session_scope

pytestmark = pytest.mark.integration


def test_dry_streak_counts_consecutive_dry_days_only() -> None:
    today = date(2026, 8, 20)
    daily = [
        DailyRainfall(date=today, total_mm=0.0),
        DailyRainfall(date=today - timedelta(days=1), total_mm=0.5),
        DailyRainfall(date=today - timedelta(days=2), total_mm=0.0),
        DailyRainfall(date=today - timedelta(days=3), total_mm=5.0),  # wet — stops here
        DailyRainfall(date=today - timedelta(days=4), total_mm=0.0),
    ]
    assert dry_streak_days(daily, threshold_mm=1.0) == 3


def test_dry_streak_stops_at_a_gap_in_the_data() -> None:
    today = date(2026, 8, 20)
    daily = [
        DailyRainfall(date=today, total_mm=0.0),
        # today-1 missing entirely — unknown, must not be assumed dry.
        DailyRainfall(date=today - timedelta(days=2), total_mm=0.0),
    ]
    assert dry_streak_days(daily, threshold_mm=1.0) == 1


def test_dry_streak_empty_is_zero() -> None:
    assert dry_streak_days([], threshold_mm=1.0) == 0


def test_dry_streak_wet_first_day_is_zero() -> None:
    today = date(2026, 8, 20)
    daily = [DailyRainfall(date=today, total_mm=10.0)]
    assert dry_streak_days(daily, threshold_mm=1.0) == 0


def test_classify_frost_days_splits_severe_and_light() -> None:
    day1 = datetime(2026, 8, 21, 6, 0, tzinfo=UTC)
    day2 = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)
    day3 = datetime(2026, 8, 23, 6, 0, tzinfo=UTC)
    points = [
        ForecastPoint(time=day1, temperature_min_c=1.5),  # severe
        ForecastPoint(time=day2, temperature_min_c=5.5),  # light
        ForecastPoint(time=day3, temperature_min_c=12.0),  # neither
    ]
    severe, light = classify_frost_days(points, severe_threshold_c=3.0, light_threshold_c=6.0)
    assert [p.time for p in severe] == [day1]
    assert [p.time for p in light] == [day2]


def test_classify_frost_days_ignores_points_without_min_temp() -> None:
    points = [ForecastPoint(time=datetime.now(UTC), temperature_min_c=None)]
    severe, light = classify_frost_days(points, severe_threshold_c=3.0, light_threshold_c=6.0)
    assert severe == []
    assert light == []


def test_classify_frost_days_boundary_is_severe_not_light() -> None:
    """Exactly at the severe threshold counts as severe, not light."""
    point = ForecastPoint(time=datetime.now(UTC), temperature_min_c=3.0)
    severe, light = classify_frost_days([point], severe_threshold_c=3.0, light_threshold_c=6.0)
    assert len(severe) == 1
    assert light == []


class _FakeProvider(WeatherProvider):
    """Deterministic stand-in — no real INMET/CPTEC call involved."""

    def __init__(self, *, frost_temp_c: float | None, dry_days: int, wet_gap: bool = False) -> None:
        self._frost_temp_c = frost_temp_c
        self._dry_days = dry_days
        self._wet_gap = wet_gap

    @property
    def name(self) -> str:
        return "FAKE"

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.STATION

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
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        return Forecast(
            provenance=self._provenance(),
            latitude=latitude,
            longitude=longitude,
            points=[ForecastPoint(time=tomorrow, temperature_min_c=self._frost_temp_c)],
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        today = datetime.now(UTC).date()
        daily = [
            DailyRainfall(
                date=today - timedelta(days=d),
                total_mm=(5.0 if (self._wet_gap and d == 3) else 0.0),
            )
            # Start from yesterday: the pipeline itself excludes "today" as
            # partial, so a fake "today" entry here would be a no-op either
            # way — kept out to make the fixture's intent unambiguous.
            for d in range(1, self._dry_days + 3)
        ]
        return RainfallHistory(
            provenance=self._provenance(), latitude=latitude, longitude=longitude, daily=daily
        )


def _make_location(
    session: Session, *, latitude: float = -21.1775, longitude: float = -47.8103
) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"agro-{unique}@example.com"
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
        name="Fazenda (teste)",
        kind="farm",
        latitude=latitude,
        longitude=longitude,
        radius_km=10,
        is_active=True,
    )
    session.add(location)
    session.flush()
    return location


def test_frost_alert_emitted_when_forecast_min_at_or_below_threshold() -> None:
    with session_scope() as session:
        # The shared dev DB may carry other real, active locations (this
        # pipeline correctly checks every one of them) — assertions here
        # are scoped to this test's own location, never to the aggregate
        # summary count, same reasoning as test_integration_satellite.py.
        location = _make_location(session)
        settings = Settings(environment="test", agro_frost_threshold_c=3.0)
        provider = _FakeProvider(frost_temp_c=2.0, dry_days=0)

        run_agro_advisory_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.FROST_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert "2.0" in alert.message
        session.rollback()


def test_light_frost_alert_uses_yellow_level_and_says_leve() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(
            environment="test", agro_frost_threshold_c=3.0, agro_frost_light_threshold_c=6.0
        )
        provider = _FakeProvider(frost_temp_c=5.5, dry_days=0)

        run_agro_advisory_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.FROST_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert alert.level == RiskLevel.YELLOW
        assert "leve" in alert.message.lower()
        assert "forte" not in alert.message.lower()
        session.rollback()


def test_no_frost_alert_when_forecast_min_above_threshold() -> None:
    with session_scope() as session:
        _make_location(session)
        settings = Settings(environment="test", agro_frost_threshold_c=3.0)
        provider = _FakeProvider(frost_temp_c=10.0, dry_days=0)

        summary = run_agro_advisory_cycle(session, settings=settings, provider=provider)

        assert summary.frost_alerts == 0
        session.rollback()


def test_dry_spell_alert_emitted_when_streak_reaches_minimum() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(
            environment="test",
            agro_frost_threshold_c=-99.0,  # never trips, isolates the dry-spell check
            agro_dry_spell_min_days=5,
            agro_dry_spell_rain_threshold_mm=1.0,
        )
        provider = _FakeProvider(frost_temp_c=15.0, dry_days=7)

        run_agro_advisory_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.DRY_SPELL_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert "dias consecutivos sem chuva" in alert.message
        assert "pelo menos" not in alert.message
        session.rollback()


def test_dry_spell_alert_says_pelo_menos_when_streak_hits_window_ceiling() -> None:
    """The streak can never exceed how many days of history were fetched —
    if it hits that ceiling, the real drought may be longer than we can
    see, so the message must say "pelo menos" instead of an exact count."""
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(
            environment="test",
            agro_frost_threshold_c=-99.0,
            agro_dry_spell_min_days=5,
            agro_dry_spell_window_days=10,
            agro_dry_spell_rain_threshold_mm=1.0,
        )
        provider = _FakeProvider(frost_temp_c=15.0, dry_days=20)

        run_agro_advisory_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.DRY_SPELL_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert "pelo menos" in alert.message
        session.rollback()


def test_dry_spell_streak_broken_by_a_wet_day_does_not_alert() -> None:
    with session_scope() as session:
        _make_location(session)
        settings = Settings(
            environment="test",
            agro_frost_threshold_c=-99.0,
            agro_dry_spell_min_days=5,
            agro_dry_spell_rain_threshold_mm=1.0,
        )
        provider = _FakeProvider(frost_temp_c=15.0, dry_days=7, wet_gap=True)

        summary = run_agro_advisory_cycle(session, settings=settings, provider=provider)

        assert summary.dry_spell_alerts == 0
        session.rollback()


def test_alert_emission_is_idempotent() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(environment="test", agro_frost_threshold_c=3.0)
        provider = _FakeProvider(frost_temp_c=2.0, dry_days=0)

        run_agro_advisory_cycle(session, settings=settings, provider=provider)
        session.flush()
        run_agro_advisory_cycle(session, settings=settings, provider=provider)

        # Same dedup_key both times — exactly one row for this location,
        # not re-emitted on the second cycle.
        count = len(
            session.scalars(
                select(Alert).where(
                    Alert.event_type == AlertEventType.FROST_WARNING,
                    Alert.location_id == location.id,
                )
            ).all()
        )
        assert count == 1
        session.rollback()


def test_disabled_returns_immediately() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", agro_enabled=False)
        summary = run_agro_advisory_cycle(session, settings=settings)
        assert summary.enabled is False
        assert summary.locations_checked == 0
