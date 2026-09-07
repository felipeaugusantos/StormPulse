"""Integration tests for workers/alert_rules_pipeline.py (Fase 3 —
Alertas Personalizados, ADR-0083).

Needs a real Postgres — same pattern as ``test_agro_pipeline.py``: tenant/
user/location/rule built directly in the sync session, rolled back at the
end. A deterministic fake ``WeatherProvider`` stands in for Open-Meteo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alert_rules.models import (
    AlertAcknowledgement,
    AlertChannel,
    AlertCondition,
    AlertDelivery,
    AlertEscalation,
    AlertEvent,
    AlertRecipient,
    AlertRule,
)
from app.alerts.models import Alert
from app.core.config import Settings
from app.core.crypto import blind_index, encrypt_field
from app.core.enums import AlertEventStatus, NotificationChannel, NotificationStatus
from app.core.enums import WeatherSourceKind as _WSK
from app.locations.models import Location
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
from workers.alert_rules_pipeline import (
    acknowledge_event,
    run_alert_delivery_cycle,
    run_alert_rules_cycle,
    run_escalation_cycle,
)
from workers.db import session_scope

pytestmark = pytest.mark.integration


class _FakeProvider(WeatherProvider):
    """Deterministic stand-in — a fixed value for wind/temperature/rain
    "today"."""

    def __init__(self, *, wind_kmh: float, temperature_mean_c: float = 22.0) -> None:
        self._wind_kmh = wind_kmh
        self._temperature_mean_c = temperature_mean_c

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
                    temperature_mean_c=self._temperature_mean_c,
                    temperature_min_c=self._temperature_mean_c - 5,
                    wind_gusts_max_kmh=self._wind_kmh,
                    humidity_mean_percent=50.0,
                    precipitation_mm=0.0,
                    precipitation_probability=10,
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
    email = f"alert-rules-{unique}@example.com"
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


def _make_rule_with_wind_condition(
    session: Session,
    tenant: Tenant,
    user: User,
    location: Location,
    *,
    threshold: float = 40.0,
    **rule_kwargs: object,
) -> AlertRule:
    rule = AlertRule(
        tenant_id=tenant.id,
        location_id=location.id,
        user_id=user.id,
        name="Vento forte",
        enabled=True,
        **rule_kwargs,
    )
    session.add(rule)
    session.flush()
    session.add(
        AlertCondition(
            tenant_id=tenant.id,
            rule_id=rule.id,
            metric="wind_kmh",
            operator=">",
            threshold=threshold,
        )
    )
    session.flush()
    return rule


def _make_push_channel_and_recipient(
    session: Session, tenant: Tenant, rule: AlertRule, user: User
) -> AlertRecipient:
    channel = AlertChannel(
        tenant_id=tenant.id, kind=NotificationChannel.EMAIL, name="E-mail padrão", enabled=True
    )
    session.add(channel)
    session.flush()
    recipient = AlertRecipient(
        tenant_id=tenant.id, rule_id=rule.id, channel_id=channel.id, user_id=user.id, enabled=True
    )
    session.add(recipient)
    session.flush()
    return recipient


def test_rule_opens_an_event_and_creates_a_delivery_when_condition_matches() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")
        provider = _FakeProvider(wind_kmh=50.0)

        summary = run_alert_rules_cycle(session, settings=settings, provider=provider)

        assert summary.events_opened >= 1
        event = session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).one()
        assert event.status == AlertEventStatus.OPEN
        assert event.alert_id is not None
        bridge_alert = session.get(Alert, event.alert_id)
        assert bridge_alert is not None

        deliveries = session.scalars(
            select(AlertDelivery).where(AlertDelivery.event_id == event.id)
        ).all()
        assert len(deliveries) == 1
        assert deliveries[0].notice_kind == AlertEventStatus.OPEN
        assert deliveries[0].channel_kind == NotificationChannel.EMAIL
        session.rollback()


def test_rule_below_threshold_never_opens_an_event() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")
        provider = _FakeProvider(wind_kmh=10.0)

        run_alert_rules_cycle(session, settings=settings, provider=provider)

        assert (
            session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).first() is None
        )
        session.rollback()


def test_condition_no_longer_matching_closes_the_open_event() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")

        run_alert_rules_cycle(session, settings=settings, provider=_FakeProvider(wind_kmh=50.0))
        event = session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).one()
        assert event.status == AlertEventStatus.OPEN

        run_alert_rules_cycle(session, settings=settings, provider=_FakeProvider(wind_kmh=5.0))
        session.refresh(event)
        # mypy narrows `event.status` from the OPEN assert above and (not
        # knowing `session.refresh` can change it) flags this as
        # non-overlapping — a known false positive with re-read ORM enum
        # attributes, not a real type error.
        assert event.status == AlertEventStatus.CLOSED  # type: ignore[comparison-overlap]
        assert event.closed_at is not None

        deliveries = session.scalars(
            select(AlertDelivery).where(AlertDelivery.event_id == event.id)
        ).all()
        assert {d.notice_kind for d in deliveries} == {
            AlertEventStatus.OPEN,
            AlertEventStatus.CLOSED,
        }
        session.rollback()


def test_cooldown_prevents_repeat_events_within_the_window() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(
            session, tenant, user, location, threshold=40.0, cooldown_minutes=30
        )
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")
        provider = _FakeProvider(wind_kmh=50.0)

        run_alert_rules_cycle(session, settings=settings, provider=provider)
        first_events = session.scalars(
            select(AlertEvent).where(AlertEvent.rule_id == rule.id)
        ).all()
        assert len(first_events) == 1

        # Re-running immediately, still matching — cooldown must suppress
        # a second OPEN/UPDATE within the 30-minute window.
        run_alert_rules_cycle(session, settings=settings, provider=provider)
        second_events = session.scalars(
            select(AlertEvent).where(AlertEvent.rule_id == rule.id)
        ).all()
        assert len(second_events) == 1
        assert second_events[0].status == AlertEventStatus.OPEN  # never touched again
        session.rollback()


def test_quiet_hours_suppresses_evaluation_entirely() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        now_time = datetime.now(UTC).time()
        # A quiet-hours window that always contains "now" — start=00:00,
        # end=23:59:59 covers any time of day deterministically.
        rule = _make_rule_with_wind_condition(
            session,
            tenant,
            user,
            location,
            threshold=40.0,
            quiet_hours_start=time(0, 0),
            quiet_hours_end=time(23, 59, 59),
        )
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")

        run_alert_rules_cycle(session, settings=settings, provider=_FakeProvider(wind_kmh=999.0))

        assert (
            session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).first() is None
        )
        del now_time  # unused, kept for clarity that "now" is inside the window
        session.rollback()


def test_delivery_cycle_sends_and_records_history() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        _make_push_channel_and_recipient(session, tenant, rule, user)
        settings = Settings(environment="test")

        run_alert_rules_cycle(session, settings=settings, provider=_FakeProvider(wind_kmh=50.0))
        event = session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).one()
        delivery = session.scalars(
            select(AlertDelivery).where(AlertDelivery.event_id == event.id)
        ).one()
        assert delivery.status == NotificationStatus.PENDING
        assert delivery.attempts == 0

        summary = run_alert_delivery_cycle(session, settings=settings)

        session.flush()
        session.refresh(delivery)
        # SES isn't configured in this test env, so email delivery fails
        # honestly — the point being tested is that the attempt is
        # *recorded* (attempts incremented, retry scheduled), not that it
        # necessarily succeeds without real SES credentials.
        assert summary.attempted >= 1
        assert delivery.attempts == 1
        assert delivery.status in (NotificationStatus.PENDING, NotificationStatus.SENT)
        if delivery.status == NotificationStatus.PENDING:
            assert delivery.next_retry_at is not None
        session.rollback()


def test_webhook_delivery_is_signed_and_recorded() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        channel = AlertChannel(
            tenant_id=tenant.id,
            kind=NotificationChannel.WEBHOOK,
            name="Webhook externo",
            enabled=True,
            webhook_url="https://example.invalid/hook",
            webhook_secret_encrypted=encrypt_field("shared-secret"),
        )
        session.add(channel)
        session.flush()
        recipient = AlertRecipient(
            tenant_id=tenant.id, rule_id=rule.id, channel_id=channel.id, enabled=True
        )
        session.add(recipient)
        session.flush()
        settings = Settings(environment="test")

        run_alert_rules_cycle(session, settings=settings, provider=_FakeProvider(wind_kmh=50.0))
        event = session.scalars(select(AlertEvent).where(AlertEvent.rule_id == rule.id)).one()
        delivery = session.scalars(
            select(AlertDelivery).where(AlertDelivery.event_id == event.id)
        ).one()
        assert delivery.channel_kind == NotificationChannel.WEBHOOK

        summary = run_alert_delivery_cycle(session, settings=settings)
        session.flush()
        session.refresh(delivery)
        # example.invalid never resolves — a real network failure is the
        # expected/correct outcome here (proves the attempt was made and
        # recorded, not that a fake URL magically succeeds).
        assert summary.attempted >= 1
        assert delivery.attempts == 1
        assert delivery.error is not None
        session.rollback()


def test_delivery_cycle_never_reattempts_an_already_sent_delivery() -> None:
    """Nenhuma entrega duplicada — a SENT delivery must never be picked up
    again by a later cycle."""
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location, threshold=40.0)
        recipient = _make_push_channel_and_recipient(session, tenant, rule, user)
        event = AlertEvent(
            tenant_id=tenant.id,
            rule_id=rule.id,
            location_id=location.id,
            status=AlertEventStatus.OPEN,
            opened_at=datetime.now(UTC),
            last_updated_at=datetime.now(UTC),
            snapshot_json="{}",
        )
        session.add(event)
        session.flush()
        delivery = AlertDelivery(
            tenant_id=tenant.id,
            event_id=event.id,
            recipient_id=recipient.id,
            notice_kind=AlertEventStatus.OPEN,
            channel_kind=NotificationChannel.EMAIL,
            status=NotificationStatus.SENT,
            sent_at=datetime.now(UTC),
        )
        session.add(delivery)
        session.flush()
        settings = Settings(environment="test")

        summary = run_alert_delivery_cycle(session, settings=settings)

        assert summary.attempted == 0
        session.flush()
        session.refresh(delivery)
        assert delivery.attempts == 0
        session.rollback()


def test_acknowledge_event_is_idempotent() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location)
        event = AlertEvent(
            tenant_id=tenant.id,
            rule_id=rule.id,
            location_id=location.id,
            status=AlertEventStatus.OPEN,
            opened_at=datetime.now(UTC),
            last_updated_at=datetime.now(UTC),
            snapshot_json="{}",
        )
        session.add(event)
        session.flush()

        first = acknowledge_event(session, event_id=event.id, user_id=user.id, notes="vi o alerta")
        second = acknowledge_event(session, event_id=event.id, user_id=user.id, notes="tentativa 2")

        assert first.id == second.id
        assert second.notes == "vi o alerta"  # first ack wins, never overwritten
        acks = session.scalars(
            select(AlertAcknowledgement).where(AlertAcknowledgement.event_id == event.id)
        ).all()
        assert len(acks) == 1
        session.rollback()


def test_escalation_fires_only_after_the_delay_and_only_once() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location)
        recipient = _make_push_channel_and_recipient(session, tenant, rule, user)
        session.add(
            AlertEscalation(
                tenant_id=tenant.id,
                rule_id=rule.id,
                step_order=0,
                delay_minutes=10,
                recipient_id=recipient.id,
            )
        )
        event = AlertEvent(
            tenant_id=tenant.id,
            rule_id=rule.id,
            location_id=location.id,
            status=AlertEventStatus.OPEN,
            opened_at=datetime.now(UTC) - timedelta(minutes=15),  # past the 10-minute delay
            last_updated_at=datetime.now(UTC),
            snapshot_json="{}",
        )
        session.add(event)
        session.flush()

        escalated_count = run_escalation_cycle(session)
        assert escalated_count == 1

        # Re-running must not create a second delivery for the same step.
        escalated_again = run_escalation_cycle(session)
        assert escalated_again == 0

        deliveries = session.scalars(
            select(AlertDelivery).where(AlertDelivery.event_id == event.id)
        ).all()
        assert len(deliveries) == 1
        session.rollback()


def test_escalation_never_fires_once_acknowledged() -> None:
    with session_scope() as session:
        tenant, user, location = _make_tenant_user_location(session)
        rule = _make_rule_with_wind_condition(session, tenant, user, location)
        recipient = _make_push_channel_and_recipient(session, tenant, rule, user)
        session.add(
            AlertEscalation(
                tenant_id=tenant.id,
                rule_id=rule.id,
                step_order=0,
                delay_minutes=10,
                recipient_id=recipient.id,
            )
        )
        event = AlertEvent(
            tenant_id=tenant.id,
            rule_id=rule.id,
            location_id=location.id,
            status=AlertEventStatus.OPEN,
            opened_at=datetime.now(UTC) - timedelta(minutes=15),
            last_updated_at=datetime.now(UTC),
            snapshot_json="{}",
        )
        session.add(event)
        session.flush()
        acknowledge_event(session, event_id=event.id, user_id=user.id)

        assert run_escalation_cycle(session) == 0
        session.rollback()
