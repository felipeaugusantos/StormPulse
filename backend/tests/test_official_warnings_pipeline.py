"""Tests for the official-warnings-to-alerts pipeline (item 3, ADR-0064).

Same pattern as test_agro_pipeline.py — a real Postgres, tenant/user/
location built directly in the sync session and rolled back at the end. A
small fake ``WeatherProvider`` stands in for INMET so this exercises only
the decision logic, not any real network shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
    Forecast,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
)
from workers.db import session_scope
from workers.official_warnings_pipeline import run_official_warnings_cycle

pytestmark = pytest.mark.integration


class _FakeProvider(WeatherProvider):
    """Deterministic stand-in — no real INMET call involved."""

    def __init__(self, warnings: list[Warning]) -> None:
        self._warnings = warnings

    @property
    def name(self) -> str:
        return "FAKE"

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.OFFICIAL_WARNING

    def _provenance(self) -> Provenance:
        return Provenance(source_name="INMET (fake)", source_kind=self.kind, is_mock=False)

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
        return self._warnings

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        return Forecast(provenance=self._provenance(), latitude=latitude, longitude=longitude)

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        return RainfallHistory(
            provenance=self._provenance(), latitude=latitude, longitude=longitude
        )


def _make_warning(*, severity: str = "perigo", kind: str = "chuva_intensa") -> Warning:
    return Warning(
        provenance=Provenance(
            source_name="INMET", source_kind=WeatherSourceKind.OFFICIAL_WARNING, is_mock=False
        ),
        issued_at=datetime.now(UTC),
        kind=kind,
        severity=severity,
        description="Chuvas intensas previstas nas próximas 24h.",
    )


def _make_location(
    session: Session, *, latitude: float = -21.1775, longitude: float = -47.8103
) -> Location:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    email = f"official-warning-{unique}@example.com"
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


def test_alert_emitted_for_an_active_official_warning() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider([_make_warning(severity="perigo")])

        run_official_warnings_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.OFFICIAL_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert alert.level == RiskLevel.ORANGE
        assert "Chuvas intensas" in alert.message
        session.rollback()


def test_severity_grande_perigo_maps_to_red() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider([_make_warning(severity="grande perigo")])

        run_official_warnings_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.OFFICIAL_WARNING,
                Alert.location_id == location.id,
            )
        ).one()
        assert alert.level == RiskLevel.RED
        session.rollback()


def test_no_warnings_creates_no_alert() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(environment="test")
        provider = _FakeProvider([])

        run_official_warnings_cycle(session, settings=settings, provider=provider)

        alert = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.OFFICIAL_WARNING,
                Alert.location_id == location.id,
            )
        ).one_or_none()
        assert alert is None
        session.rollback()


def test_alert_emission_is_idempotent() -> None:
    with session_scope() as session:
        location = _make_location(session)
        settings = Settings(environment="test")
        warning = _make_warning()
        provider = _FakeProvider([warning])

        run_official_warnings_cycle(session, settings=settings, provider=provider)
        run_official_warnings_cycle(session, settings=settings, provider=provider)

        alerts = session.scalars(
            select(Alert).where(
                Alert.event_type == AlertEventType.OFFICIAL_WARNING,
                Alert.location_id == location.id,
            )
        ).all()
        assert len(alerts) == 1
        session.rollback()


def test_disabled_returns_immediately() -> None:
    with session_scope() as session:
        settings = Settings(environment="test", official_warnings_enabled=False)
        summary = run_official_warnings_cycle(
            session, settings=settings, provider=_FakeProvider([])
        )
        assert summary.enabled is False
        session.rollback()
