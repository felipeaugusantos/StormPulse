"""Push notification delivery pipeline (FASE 22; Expo/mobile since FASE 26).

Fans out ``Notification`` rows left ``PENDING`` by the other pipelines
(``agro_pipeline.py``, ``satellite_pipeline.py``, ``pipeline_service.py`` —
each already creates one Notification per Alert it emits, see their
``_emit_alert``/equivalent helpers) to every push registration the target
user has (``PushSubscription``, see ``app/notifications/models.py``) — a
browser's Web Push subscription or the mobile app's Expo push token,
branching delivery on ``PushSubscription.platform``.

No FCM/APNs account needed for either path — Web Push is a browser-native
standard (the only "infra" is a VAPID keypair, ``vapid_private_key``/
``vapid_public_key`` in ``Settings``); Expo's push API accepts a bare push
token with no server credential at all. A cycle is never skipped just
because VAPID is missing (mobile-only deployments must still deliver) —
``configured`` on the summary reports whether Web Push specifically is set
up; a ``platform="web"`` subscription without it fails honestly instead of
silently pretending to deliver. See ADR-0016 and ADR-0023.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import NotificationStatus
from app.notifications.models import Notification, PushSubscription

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class NotificationDeliverySummary:
    configured: bool
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    suppressed: int = 0


def _payload_dict(alert: Alert) -> dict[str, str]:
    return {"title": alert.title, "body": alert.message, "level": alert.level.value}


def _deliver_web(
    session: Session,
    subscription: PushSubscription,
    payload: dict[str, str],
    settings: Settings,
) -> tuple[bool, str | None]:
    if settings.vapid_private_key is None or settings.vapid_public_key is None:
        return False, "VAPID não configurado — push web indisponível"
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key.get_secret_value(),
            vapid_claims={"sub": settings.vapid_subject},
        )
        return True, None
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            # Expired/invalid registration (browser unsubscribed, or the
            # endpoint rotated) — stop trying it, it'll never succeed.
            session.delete(subscription)
        return False, str(exc)


def _deliver_expo(
    subscription: PushSubscription,
    payload: dict[str, str],
    client: httpx.Client,
    session: Session,
) -> tuple[bool, str | None]:
    """Expo's push API needs no server credential — a bare token is enough
    (unlike Web Push's VAPID keypair). One HTTP call per token; Expo also
    supports batching but the delivery pipeline already loops one
    notification/subscription at a time, so batching isn't worth the extra
    bookkeeping here."""
    try:
        response = client.post(
            _EXPO_PUSH_URL,
            json={
                "to": subscription.expo_push_token,
                "title": payload["title"],
                "body": payload["body"],
                "data": {"level": payload["level"]},
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        ticket = response.json().get("data", {})
    except httpx.HTTPError as exc:
        return False, str(exc)

    if ticket.get("status") == "ok":
        return True, None

    error_detail = ticket.get("details", {}).get("error")
    if error_detail == "DeviceNotRegistered":
        # Uninstalled app or revoked token — will never succeed again.
        session.delete(subscription)
    return False, ticket.get("message") or "Expo push recusado"


def _deliver_to_subscriptions(
    session: Session,
    subscriptions: list[PushSubscription],
    alert: Alert,
    settings: Settings,
    expo_client: httpx.Client,
) -> tuple[bool, str | None]:
    """Try every registration for a user (web + mobile); return (sent to at
    least one?, last error)."""
    payload = _payload_dict(alert)
    sent_to_any = False
    last_error: str | None = None
    for subscription in subscriptions:
        if subscription.platform == "expo":
            ok, error = _deliver_expo(subscription, payload, expo_client, session)
        else:
            ok, error = _deliver_web(session, subscription, payload, settings)
        if ok:
            sent_to_any = True
        elif error:
            last_error = error
    return sent_to_any, last_error


def run_notification_delivery_cycle(
    session: Session, *, settings: Settings | None = None, expo_client: httpx.Client | None = None
) -> NotificationDeliverySummary:
    """``configured`` reports whether Web Push (VAPID) is set up — Expo push
    needs no such configuration, so it's always attempted for any
    ``platform="expo"`` subscription regardless of this flag. A cycle isn't
    skipped just because VAPID is missing: mobile-only deployments must
    still deliver."""
    settings = settings or get_settings()
    web_configured = (
        settings.vapid_private_key is not None and settings.vapid_public_key is not None
    )

    pending = list(
        session.scalars(
            select(Notification).where(Notification.status == NotificationStatus.PENDING)
        )
    )
    summary = NotificationDeliverySummary(configured=web_configured)
    client = expo_client or httpx.Client(timeout=10.0)

    try:
        for notification in pending:
            summary.attempted += 1
            alert = session.get(Alert, notification.alert_id)
            if alert is None:
                notification.status = NotificationStatus.FAILED
                notification.error = "alerta associado não encontrado"
                summary.failed += 1
                continue

            subscriptions = list(
                session.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == notification.user_id)
                )
            )
            if not subscriptions:
                notification.status = NotificationStatus.SUPPRESSED
                summary.suppressed += 1
                continue

            sent_to_any, last_error = _deliver_to_subscriptions(
                session, subscriptions, alert, settings, client
            )
            if sent_to_any:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now(UTC)
                summary.sent += 1
            else:
                notification.status = NotificationStatus.FAILED
                notification.error = last_error or "todas as assinaturas expiraram ou falharam"
                summary.failed += 1
    finally:
        if expo_client is None:
            client.close()

    return summary
