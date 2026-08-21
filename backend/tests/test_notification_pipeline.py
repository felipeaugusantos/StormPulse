"""Tests for the push notification delivery pipeline (FASE 22).

Same pattern as ``test_agro_pipeline.py``: tenant/user/alert/notification
built directly in the sync session and rolled back at the end, never
committed. ``pywebpush.webpush`` is monkeypatched (module-level import in
``workers.notification_pipeline``) so nothing ever calls a real push
service.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pywebpush import WebPushException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings
from app.core.enums import AlertEventType, NotificationStatus, RiskLevel
from app.locations.models import Location
from app.notifications.models import Notification, PushSubscription
from app.tenants.models import Tenant
from app.users.models import User
from workers.db import session_scope
from workers.notification_pipeline import run_notification_delivery_cycle

pytestmark = pytest.mark.integration

_VAPID_SETTINGS = Settings(
    environment="test",
    vapid_private_key="ZLNsuj1E8lAU88nuqNbEBqhuVf8mtOVB0HOw1H7ygAQ",
    vapid_public_key="BObIJ0hf-fr8Qt9lkwfPXmQznPpM5vJVrWVZDUDQEbpf5C3YgkV44sDWnC2eddVt2MACtbCurq_IRxtL9I4lauo",
)


def _make_user_and_alert(session: Session) -> tuple[User, Alert]:
    unique = uuid.uuid4().hex
    tenant = Tenant(name=f"Test {unique}", slug=f"test-{unique}")
    session.add(tenant)
    session.flush()
    user = User(
        tenant_id=tenant.id,
        email=f"push-{unique}@example.com",
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
        latitude=-21.1775,
        longitude=-47.8103,
        radius_km=10,
        is_active=True,
    )
    session.add(location)
    session.flush()
    alert = Alert(
        tenant_id=tenant.id,
        user_id=user.id,
        location_id=location.id,
        event_type=AlertEventType.FROST_WARNING,
        level=RiskLevel.RED,
        title="Geada prevista",
        message="Mínima de 2°C prevista para amanhã",
        dedup_key=f"test:{unique}",
    )
    session.add(alert)
    session.flush()
    return user, alert


def test_cycle_reports_web_push_not_configured_without_vapid_key() -> None:
    with session_scope() as session:
        summary = run_notification_delivery_cycle(session, settings=Settings(environment="test"))
        assert summary.configured is False
        session.rollback()


def test_web_subscription_fails_without_vapid_configured() -> None:
    """Expo needs no server credential, but Web Push does — a web
    subscription without VAPID configured must fail loudly, not silently
    no-op the whole cycle (FASE 26 changed this from an early return)."""
    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id,
                user_id=user.id,
                platform="web",
                endpoint="https://push.example.com/no-vapid",
                p256dh="fake-p256dh",
                auth="fake-auth",
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        run_notification_delivery_cycle(session, settings=Settings(environment="test"))

        assert notification.status == NotificationStatus.FAILED
        session.rollback()


def test_expo_subscription_delivers_without_vapid_configured(monkeypatch: Any) -> None:
    """Mobile-only deployments (no VAPID at all) must still deliver."""

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": {"status": "ok"}}

    class _FakeClient:
        def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse()

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id,
                user_id=user.id,
                platform="expo",
                expo_push_token=f"ExponentPushToken[{uuid.uuid4().hex}]",
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        run_notification_delivery_cycle(
            session,
            settings=Settings(environment="test"),
            expo_client=_FakeClient(),  # type: ignore[arg-type]
        )

        assert notification.status == NotificationStatus.SENT
        session.rollback()


def test_expo_device_not_registered_deletes_subscription(monkeypatch: Any) -> None:
    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": {
                    "status": "error",
                    "message": "not registered",
                    "details": {"error": "DeviceNotRegistered"},
                }
            }

    class _FakeClient:
        def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse()

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        token = f"ExponentPushToken[{uuid.uuid4().hex}]"
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id, user_id=user.id, platform="expo", expo_push_token=token
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        run_notification_delivery_cycle(
            session,
            settings=Settings(environment="test"),
            expo_client=_FakeClient(),  # type: ignore[arg-type]
        )

        assert notification.status == NotificationStatus.FAILED
        remaining = session.scalars(
            select(PushSubscription).where(PushSubscription.expo_push_token == token)
        ).first()
        assert remaining is None
        session.rollback()


def test_notification_suppressed_when_user_has_no_subscription() -> None:
    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        # The shared dev DB may carry other real, pending notifications from
        # earlier test runs — assert on this test's own row, never the
        # aggregate count, same reasoning as test_agro_pipeline.py.
        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.SUPPRESSED
        session.rollback()


def test_notification_sent_when_webpush_succeeds(monkeypatch: Any) -> None:
    import workers.notification_pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "webpush", lambda **kwargs: None)

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id,
                user_id=user.id,
                endpoint="https://push.example.com/abc",
                p256dh="fake-p256dh",
                auth="fake-auth",
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        # Scoped to this test's own row, not the aggregate — see the
        # suppressed-notification test above for why.
        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.SENT
        assert notification.sent_at is not None
        session.rollback()


def test_expired_subscription_is_deleted_and_notification_failed(monkeypatch: Any) -> None:
    import workers.notification_pipeline as pipeline_module

    class _FakeResponse:
        status_code = 410

    def _raise_gone(**kwargs: Any) -> None:
        raise WebPushException("gone", response=_FakeResponse())

    monkeypatch.setattr(pipeline_module, "webpush", _raise_gone)

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        endpoint = f"https://push.example.com/{uuid.uuid4().hex}"
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id,
                user_id=user.id,
                endpoint=endpoint,
                p256dh="fake-p256dh",
                auth="fake-auth",
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        # Scoped to this test's own row, not the aggregate — see the
        # suppressed-notification test above for why.
        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.FAILED

        remaining = session.scalars(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        assert remaining is None
        session.rollback()
