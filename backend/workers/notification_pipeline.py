"""Push notification delivery pipeline (FASE 22).

Fans out ``Notification`` rows left ``PENDING`` by the other pipelines
(``agro_pipeline.py``, ``satellite_pipeline.py``, ``pipeline_service.py`` —
each already creates one Notification per Alert it emits, see their
``_emit_alert``/equivalent helpers) to every Web Push subscription the
target user has registered from their browser (``PushSubscription``, see
``app/notifications/models.py``).

No FCM/APNs account needed — Web Push is a browser-native standard, the only
"infra" is a VAPID keypair generated once locally (``vapid_private_key``/
``vapid_public_key`` in ``Settings``). Without a configured key, every cycle
is an honest no-op (``configured=False``) rather than silently pretending to
deliver. See ADR-0016.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import NotificationStatus
from app.notifications.models import Notification, PushSubscription

logger = logging.getLogger(__name__)


@dataclass
class NotificationDeliverySummary:
    configured: bool
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    suppressed: int = 0


def _payload(alert: Alert) -> str:
    return json.dumps({"title": alert.title, "body": alert.message, "level": alert.level.value})


def _deliver_to_subscriptions(
    session: Session,
    subscriptions: list[PushSubscription],
    data: str,
    settings: Settings,
) -> tuple[bool, str | None]:
    """Try every subscription for a user; return (sent to at least one?, last error)."""
    assert settings.vapid_private_key is not None  # guarded by the caller

    sent_to_any = False
    last_error: str | None = None
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=data,
                vapid_private_key=settings.vapid_private_key.get_secret_value(),
                vapid_claims={"sub": settings.vapid_subject},
            )
            sent_to_any = True
        except WebPushException as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code in (404, 410):
                # Expired/invalid registration (browser unsubscribed, or the
                # endpoint rotated) — stop trying it, it'll never succeed.
                session.delete(subscription)
            else:
                last_error = str(exc)
    return sent_to_any, last_error


def run_notification_delivery_cycle(
    session: Session, *, settings: Settings | None = None
) -> NotificationDeliverySummary:
    settings = settings or get_settings()
    if settings.vapid_private_key is None or settings.vapid_public_key is None:
        return NotificationDeliverySummary(configured=False)

    pending = list(
        session.scalars(
            select(Notification).where(Notification.status == NotificationStatus.PENDING)
        )
    )
    summary = NotificationDeliverySummary(configured=True)

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
            session, subscriptions, _payload(alert), settings
        )
        if sent_to_any:
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(UTC)
            summary.sent += 1
        else:
            notification.status = NotificationStatus.FAILED
            notification.error = last_error or "todas as assinaturas expiraram ou falharam"
            summary.failed += 1

    return summary
