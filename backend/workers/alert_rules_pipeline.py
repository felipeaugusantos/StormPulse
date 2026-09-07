"""Custom alert rule evaluation cycle (Fase 3 — Alertas Personalizados,
ADR-0083).

Mirrors ``workers/agro_pipeline.py``'s structure (own decision logic,
per-rule error isolation). Two independent cycles, same split as
``workers/forecast_comparison_pipeline.py``:

- ``run_alert_rules_cycle`` — gathers each active rule's location signals
  into an ``engine.alert_rules.MetricSnapshot``, evaluates conditions,
  applies quiet hours/cooldown, and manages the ``AlertEvent`` lifecycle
  (open → updated → closed). Each transition bridges a real ``Alert`` row
  (same as every other pipeline in this project — event_type=CUSTOM_RULE)
  so push/email delivery can reuse ``notification_pipeline.py``'s existing,
  tested delivery functions unchanged, and so custom-rule alerts show up
  in the normal ``/alerts`` feed. Fans out an ``AlertDelivery`` row per
  recipient for whichever notice kind fired.
- ``run_alert_delivery_cycle`` — sends whatever's PENDING/retry-due in
  ``AlertDelivery``. PUSH/EMAIL reuse ``notification_pipeline.py``'s
  ``_deliver_to_subscriptions``/``_deliver_email`` against the bridged
  Alert; WEBHOOK (real, HMAC-signed) and WHATSAPP/SMS (mock) are new,
  ``app/alert_rules/providers.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
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
from app.alert_rules.providers import (
    MockWhatsAppSmsProvider,
    WhatsAppSmsProviderUnavailableError,
    send_webhook,
)
from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.crypto import decrypt_field
from app.core.enums import (
    AlertEventStatus,
    AlertEventType,
    NotificationChannel,
    NotificationStatus,
    RiskLevel,
)
from app.lightning.models import LightningStrike
from app.locations.models import Location
from app.notifications.models import PushSubscription
from app.soilmoisture.factory import get_soil_moisture_provider
from app.soilmoisture.provider import SoilMoistureProviderUnavailableError
from app.storms.models import StormRisk
from app.users.models import User
from app.weather.factory import get_numeric_rain_forecast_provider
from app.weather.provider import WeatherProvider, WeatherProviderUnavailableError
from engine.agro import classify_disease_risk, vapor_pressure_deficit_kpa
from engine.alert_rules import AlertCondition as EngineCondition
from engine.alert_rules import (
    MetricSnapshot,
    evaluate_conditions,
    is_in_cooldown,
    is_within_quiet_hours,
)
from engine.geo import haversine_km
from workers.notification_pipeline import _deliver_email, _deliver_to_subscriptions

logger = logging.getLogger(__name__)

_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)
_MAX_DELIVERY_ATTEMPTS = 5

# Same defaults already used client-side (web/src/agro.ts, mobile/src/
# screens/AgroScreen.tsx) — a daily proxy for fungal disease pressure, not
# crop-specific (see engine/agro.py::classify_disease_risk docstring).
_DISEASE_HUMIDITY_THRESHOLD_PERCENT = 80.0
_DISEASE_MIN_TEMP_C = 15.0
_DISEASE_MAX_TEMP_C = 30.0

# How recent a lightning strike must be to count toward
# `lightning_distance_km` — matches LIGHTNING_RETENTION_MINUTES' spirit
# (a snapshot of "now", not a historical search).
_LIGHTNING_LOOKBACK_MINUTES = 30

# A custom rule has no inherent severity the way a storm-cell hazard score
# does — OPEN/UPDATED get a middle tier (the user opted into this rule
# mattering to them), CLOSED reuses GREEN ("tudo seguro", same meaning it
# has everywhere else in this codebase).
_NOTICE_LEVEL: dict[AlertEventStatus, RiskLevel] = {
    AlertEventStatus.OPEN: RiskLevel.ORANGE,
    AlertEventStatus.UPDATED: RiskLevel.ORANGE,
    AlertEventStatus.CLOSED: RiskLevel.GREEN,
}

_whatsapp_sms_provider = MockWhatsAppSmsProvider()


@dataclass
class AlertRulesCycleSummary:
    rules_evaluated: int = 0
    events_opened: int = 0
    events_updated: int = 0
    events_closed: int = 0
    deliveries_created: int = 0


@dataclass
class AlertDeliveryCycleSummary:
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    retrying: int = 0


# ---------------------------------------------------------------------------
# Metric gathering
# ---------------------------------------------------------------------------


async def gather_metric_snapshot(
    location: Location,
    settings: Settings,
    session: Session,
    *,
    provider: WeatherProvider | None = None,
) -> MetricSnapshot:
    """Best-effort — any single source failing degrades that source's
    metrics to `None` (never invented), the rest still populate.
    ``provider`` is injectable (tests pass a deterministic fake) — defaults
    to the real Open-Meteo-direct provider (ADR-0020), same as every other
    call site of ``get_numeric_rain_forecast_provider``."""
    rain_mm = rain_probability_percent = wind_kmh = None
    temperature_c = frost_temperature_c = vpd_kpa = None
    disease_risk_high: float | None = None
    soil_moisture_percent = None

    provider = provider or get_numeric_rain_forecast_provider(settings)
    try:
        forecast = await provider.get_forecast(location.latitude, location.longitude)
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        upcoming = [p for p in forecast.points if p.time >= today]
        point = upcoming[0] if upcoming else None
        if point is not None:
            rain_mm = point.precipitation_mm
            rain_probability_percent = (
                float(point.precipitation_probability)
                if point.precipitation_probability is not None
                else None
            )
            wind_kmh = point.wind_gusts_max_kmh
            temperature_c = point.temperature_mean_c
            frost_temperature_c = point.temperature_min_c
            if point.temperature_mean_c is not None and point.humidity_mean_percent is not None:
                vpd_kpa = vapor_pressure_deficit_kpa(
                    point.temperature_mean_c, point.humidity_mean_percent
                )
            disease = classify_disease_risk(
                point.humidity_mean_percent,
                point.temperature_mean_c,
                humidity_threshold_percent=_DISEASE_HUMIDITY_THRESHOLD_PERCENT,
                min_temp_c=_DISEASE_MIN_TEMP_C,
                max_temp_c=_DISEASE_MAX_TEMP_C,
            )
            if disease != "unknown":
                disease_risk_high = 1.0 if disease == "high" else 0.0
    except _RECOVERABLE as exc:
        logger.warning("alert_rules: forecast unavailable for location %s (%s)", location.id, exc)

    if settings.soil_moisture_enabled:
        soil_provider = get_soil_moisture_provider(settings)
        try:
            observation = await soil_provider.get_soil_moisture(
                location.latitude, location.longitude
            )
            soil_moisture_percent = observation.surface_wetness_percent
        except (SoilMoistureProviderUnavailableError, *_RECOVERABLE) as exc:
            logger.warning(
                "alert_rules: soil moisture unavailable for location %s (%s)", location.id, exc
            )
        finally:
            await soil_provider.aclose()

    return MetricSnapshot(
        rain_mm=rain_mm,
        rain_probability_percent=rain_probability_percent,
        wind_kmh=wind_kmh,
        temperature_c=temperature_c,
        frost_temperature_c=frost_temperature_c,
        vpd_kpa=vpd_kpa,
        soil_moisture_percent=soil_moisture_percent,
        disease_risk_high=disease_risk_high,
        lightning_distance_km=_nearest_lightning_distance_km(session, location),
        storm_eta_minutes=_latest_storm_eta_minutes(session, location),
    )


def _nearest_lightning_distance_km(session: Session, location: Location) -> float | None:
    since = datetime.now(UTC) - timedelta(minutes=_LIGHTNING_LOOKBACK_MINUTES)
    strikes = session.scalars(
        select(LightningStrike).where(LightningStrike.detected_at >= since)
    ).all()
    if not strikes:
        return None
    return min(
        haversine_km(location.latitude, location.longitude, s.latitude, s.longitude)
        for s in strikes
    )


def _latest_storm_eta_minutes(session: Session, location: Location) -> float | None:
    risk = session.scalars(
        select(StormRisk)
        .where(StormRisk.location_id == location.id, StormRisk.eta_minutes.is_not(None))
        .order_by(StormRisk.computed_at.desc())
        .limit(1)
    ).first()
    return float(risk.eta_minutes) if risk is not None and risk.eta_minutes is not None else None


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def _rule_conditions(session: Session, rule_id: object) -> list[EngineCondition]:
    rows = session.scalars(select(AlertCondition).where(AlertCondition.rule_id == rule_id)).all()
    return [
        EngineCondition(
            metric=r.metric,  # type: ignore[arg-type]
            operator=r.operator,  # type: ignore[arg-type]
            threshold=r.threshold,
            group=r.group_index,
        )
        for r in rows
    ]


def run_alert_rules_cycle(
    session: Session, *, settings: Settings | None = None, provider: WeatherProvider | None = None
) -> AlertRulesCycleSummary:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    summary = AlertRulesCycleSummary()

    rules = session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
    for rule in rules:
        summary.rules_evaluated += 1
        try:
            _evaluate_one_rule(session, rule, settings, now, summary, provider=provider)
        except Exception:  # noqa: BLE001 - one rule's failure must never stop the cycle
            logger.exception("alert_rules: evaluation failed for rule %s", rule.id)

    return summary


def _evaluate_one_rule(
    session: Session,
    rule: AlertRule,
    settings: Settings,
    now: datetime,
    summary: AlertRulesCycleSummary,
    *,
    provider: WeatherProvider | None = None,
) -> None:
    location = session.get(Location, rule.location_id)
    if location is None or not location.is_active:
        return

    if is_within_quiet_hours(now.time(), rule.quiet_hours_start, rule.quiet_hours_end):
        return

    snapshot = asyncio.run(gather_metric_snapshot(location, settings, session, provider=provider))
    conditions = _rule_conditions(session, rule.id)
    matches = evaluate_conditions(conditions, snapshot)

    open_event = session.scalars(
        select(AlertEvent).where(
            AlertEvent.rule_id == rule.id, AlertEvent.status != AlertEventStatus.CLOSED
        )
    ).first()

    if matches:
        if is_in_cooldown(rule.last_fired_at, now, rule.cooldown_minutes):
            return
        if open_event is None:
            _transition_event(
                session, rule, location, None, AlertEventStatus.OPEN, snapshot, now, summary
            )
        else:
            _transition_event(
                session,
                rule,
                location,
                open_event,
                AlertEventStatus.UPDATED,
                snapshot,
                now,
                summary,
            )
        rule.last_fired_at = now
    elif open_event is not None:
        _transition_event(
            session, rule, location, open_event, AlertEventStatus.CLOSED, snapshot, now, summary
        )


def _snapshot_json(snapshot: MetricSnapshot) -> str:
    return json.dumps(
        {
            "rain_mm": snapshot.rain_mm,
            "rain_probability_percent": snapshot.rain_probability_percent,
            "wind_kmh": snapshot.wind_kmh,
            "temperature_c": snapshot.temperature_c,
            "frost_temperature_c": snapshot.frost_temperature_c,
            "vpd_kpa": snapshot.vpd_kpa,
            "soil_moisture_percent": snapshot.soil_moisture_percent,
            "disease_risk_high": snapshot.disease_risk_high,
            "lightning_distance_km": snapshot.lightning_distance_km,
            "storm_eta_minutes": snapshot.storm_eta_minutes,
        }
    )


_NOTICE_TITLE = {
    AlertEventStatus.OPEN: "Alerta iniciado",
    AlertEventStatus.UPDATED: "Alerta atualizado",
    AlertEventStatus.CLOSED: "Alerta encerrado — tudo seguro",
}


def _transition_event(
    session: Session,
    rule: AlertRule,
    location: Location,
    event: AlertEvent | None,
    notice_kind: AlertEventStatus,
    snapshot: MetricSnapshot,
    now: datetime,
    summary: AlertRulesCycleSummary,
) -> None:
    title = f"{_NOTICE_TITLE[notice_kind]}: {rule.name}"
    message = f'Regra "{rule.name}" em {location.name} — {_NOTICE_TITLE[notice_kind].lower()}.'

    bridge_alert = Alert(
        tenant_id=rule.tenant_id,
        user_id=rule.user_id,
        location_id=location.id,
        event_type=AlertEventType.CUSTOM_RULE,
        level=_NOTICE_LEVEL[notice_kind],
        title=title,
        message=message,
        dedup_key=f"custom_rule:{rule.id}:{notice_kind.value}:{now.isoformat()}",
    )
    session.add(bridge_alert)
    session.flush()

    if event is None:
        event = AlertEvent(
            tenant_id=rule.tenant_id,
            rule_id=rule.id,
            location_id=location.id,
            alert_id=bridge_alert.id,
            status=AlertEventStatus.OPEN,
            opened_at=now,
            last_updated_at=now,
            snapshot_json=_snapshot_json(snapshot),
        )
        session.add(event)
        summary.events_opened += 1
    else:
        event.status = notice_kind
        event.last_updated_at = now
        event.alert_id = bridge_alert.id
        event.snapshot_json = _snapshot_json(snapshot)
        if notice_kind == AlertEventStatus.CLOSED:
            event.closed_at = now
            summary.events_closed += 1
        else:
            summary.events_updated += 1
    session.flush()

    summary.deliveries_created += _create_deliveries(
        session, event=event, rule_id=rule.id, notice_kind=notice_kind
    )


def _create_deliveries(
    session: Session, *, event: AlertEvent, rule_id: object, notice_kind: AlertEventStatus
) -> int:
    recipients = session.scalars(
        select(AlertRecipient).where(
            AlertRecipient.rule_id == rule_id, AlertRecipient.enabled.is_(True)
        )
    ).all()
    created = 0
    for recipient in recipients:
        channel = session.get(AlertChannel, recipient.channel_id)
        if channel is None or not channel.enabled:
            continue
        session.add(
            AlertDelivery(
                tenant_id=event.tenant_id,
                event_id=event.id,
                recipient_id=recipient.id,
                notice_kind=notice_kind,
                channel_kind=channel.kind,
                status=NotificationStatus.PENDING,
            )
        )
        created += 1
    return created


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def run_alert_delivery_cycle(
    session: Session, *, settings: Settings | None = None
) -> AlertDeliveryCycleSummary:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    deliveries = session.scalars(
        select(AlertDelivery).where(
            AlertDelivery.status == NotificationStatus.PENDING,
            (AlertDelivery.next_retry_at.is_(None)) | (AlertDelivery.next_retry_at <= now),
        )
    ).all()

    summary = AlertDeliveryCycleSummary()
    for delivery in deliveries:
        summary.attempted += 1
        ok, error = _attempt_delivery(session, delivery, settings)
        if ok:
            delivery.status = NotificationStatus.SENT
            delivery.sent_at = now
            summary.sent += 1
        else:
            delivery.attempts += 1
            delivery.error = error
            if delivery.attempts >= _MAX_DELIVERY_ATTEMPTS:
                delivery.status = NotificationStatus.FAILED
                summary.failed += 1
            else:
                delivery.next_retry_at = now + timedelta(
                    seconds=120 * (1 << (delivery.attempts - 1))
                )
                summary.retrying += 1
    return summary


def _attempt_delivery(
    session: Session, delivery: AlertDelivery, settings: Settings
) -> tuple[bool, str | None]:
    recipient = session.get(AlertRecipient, delivery.recipient_id)
    if recipient is None:
        return False, "recipient not found"
    channel = session.get(AlertChannel, recipient.channel_id)
    if channel is None:
        return False, "channel not found"
    event = session.get(AlertEvent, delivery.event_id)
    if event is None:
        return False, "event not found"
    bridge_alert = session.get(Alert, event.alert_id) if event.alert_id else None

    if delivery.channel_kind == NotificationChannel.PUSH:
        if recipient.user_id is None or bridge_alert is None:
            return False, "push recipient/alert missing"
        subscriptions = list(
            session.scalars(
                select(PushSubscription).where(PushSubscription.user_id == recipient.user_id)
            )
        )
        if not subscriptions:
            return False, "no push subscriptions"
        with httpx.Client(timeout=10.0) as client:
            return _deliver_to_subscriptions(session, subscriptions, bridge_alert, settings, client)

    if delivery.channel_kind == NotificationChannel.EMAIL:
        if recipient.user_id is None or bridge_alert is None:
            return False, "email recipient/alert missing"
        user = session.get(User, recipient.user_id)
        if user is None:
            return False, "user not found"
        return _deliver_email(user, bridge_alert, settings)

    if delivery.channel_kind == NotificationChannel.WEBHOOK:
        if not channel.webhook_url or not channel.webhook_secret_encrypted:
            return False, "webhook not configured"
        return asyncio.run(_deliver_webhook(channel, event, delivery))

    if delivery.channel_kind in (NotificationChannel.WHATSAPP, NotificationChannel.SMS):
        if not channel.phone_number:
            return False, "phone number not configured"
        return asyncio.run(_deliver_whatsapp_sms(channel, delivery))

    return False, f"unsupported channel {delivery.channel_kind}"


async def _deliver_webhook(
    channel: AlertChannel, event: AlertEvent, delivery: AlertDelivery
) -> tuple[bool, str | None]:
    secret = decrypt_field(channel.webhook_secret_encrypted)  # type: ignore[arg-type]
    body = json.dumps(
        {
            "event_id": str(event.id),
            "rule_id": str(event.rule_id),
            "status": delivery.notice_kind.value,
        }
    ).encode("utf-8")
    try:
        async with httpx.AsyncClient() as client:
            await send_webhook(url=channel.webhook_url, secret=secret, body=body, client=client)  # type: ignore[arg-type]
        return True, None
    except httpx.HTTPError as exc:
        return False, str(exc)


async def _deliver_whatsapp_sms(
    channel: AlertChannel, delivery: AlertDelivery
) -> tuple[bool, str | None]:
    try:
        await _whatsapp_sms_provider.send(
            phone_number=channel.phone_number,  # type: ignore[arg-type]
            message=f"StormPulse: {delivery.notice_kind.value}",
        )
        return True, None
    except WhatsAppSmsProviderUnavailableError as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Acknowledgement + escalation
# ---------------------------------------------------------------------------


def acknowledge_event(
    session: Session, *, event_id: object, user_id: object, notes: str | None = None
) -> AlertAcknowledgement:
    """Idempotent — re-acking an already-acked event just returns the
    existing row (first ack wins, see AlertAcknowledgement's own
    docstring)."""
    existing = session.scalars(
        select(AlertAcknowledgement).where(AlertAcknowledgement.event_id == event_id)
    ).first()
    if existing is not None:
        return existing
    event = session.get(AlertEvent, event_id)
    if event is None:
        raise ValueError(f"AlertEvent {event_id} not found")
    ack = AlertAcknowledgement(
        tenant_id=event.tenant_id,
        event_id=event_id,
        acknowledged_by=user_id,
        acknowledged_at=datetime.now(UTC),
        notes=notes,
    )
    session.add(ack)
    session.flush()
    return ack


def run_escalation_cycle(session: Session) -> int:
    """For every non-closed event without an acknowledgement, whose age has
    crossed an escalation step's delay, creates an AlertDelivery row for
    that step's recipient — once (a step already escalated for this
    event/notice-kind always has at least one delivery already recorded,
    which is what makes re-running this idempotent)."""
    now = datetime.now(UTC)
    open_events = session.scalars(
        select(AlertEvent).where(AlertEvent.status != AlertEventStatus.CLOSED)
    ).all()

    escalated = 0
    for event in open_events:
        acked = session.scalars(
            select(AlertAcknowledgement).where(AlertAcknowledgement.event_id == event.id)
        ).first()
        if acked is not None:
            continue

        steps = session.scalars(
            select(AlertEscalation)
            .where(AlertEscalation.rule_id == event.rule_id, AlertEscalation.enabled.is_(True))
            .order_by(AlertEscalation.step_order)
        ).all()
        for step in steps:
            if now < event.opened_at + timedelta(minutes=step.delay_minutes):
                continue
            already = session.scalars(
                select(AlertDelivery).where(
                    AlertDelivery.event_id == event.id,
                    AlertDelivery.recipient_id == step.recipient_id,
                    AlertDelivery.notice_kind == event.status,
                )
            ).first()
            if already is not None:
                continue
            recipient = session.get(AlertRecipient, step.recipient_id)
            if recipient is None:
                continue
            channel = session.get(AlertChannel, recipient.channel_id)
            if channel is None:
                continue
            session.add(
                AlertDelivery(
                    tenant_id=event.tenant_id,
                    event_id=event.id,
                    recipient_id=step.recipient_id,
                    notice_kind=event.status,
                    channel_kind=channel.kind,
                    status=NotificationStatus.PENDING,
                )
            )
            escalated += 1
    return escalated
