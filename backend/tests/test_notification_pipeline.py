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
from app.core.crypto import blind_index
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
    email = f"push-{unique}@example.com"
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


def test_web_subscription_without_vapid_configured_retries_not_fails_outright() -> None:
    """Expo needs no server credential, but Web Push does — a web
    subscription without VAPID configured must fail loudly, not silently
    no-op the whole cycle (FASE 26 changed this from an early return).
    A single failure retries (item "notificação falhada é terminal") —
    it isn't permanently FAILED until attempts are exhausted."""
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

        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1
        assert notification.next_retry_at is not None
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


def test_expo_device_not_registered_deletes_subscription_and_retries(monkeypatch: Any) -> None:
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

        # The subscription is unrecoverable and correctly removed right
        # away; the *notification* still gets its retry budget (a later
        # cycle might reach the user by email instead).
        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1
        remaining = session.scalars(
            select(PushSubscription).where(PushSubscription.expo_push_token == token)
        ).first()
        assert remaining is None
        session.rollback()


def test_notification_retries_when_no_subscription_and_email_unconfigured() -> None:
    """Item e-mail de alerta changed what "no push subscription" means: a
    real user's own email is always attempted too, regardless of push —
    so no-subscription-and-SES-not-configured is a real delivery failure
    (both channels tried, neither worked), not `SUPPRESSED` (which used to
    mean "nothing to even try"). It retries rather than failing outright —
    item "notificação falhada é terminal"."""
    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        # The shared dev DB may carry other real, pending notifications from
        # earlier test runs — assert on this test's own row, never the
        # aggregate count, same reasoning as test_agro_pipeline.py.
        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1
        assert notification.next_retry_at is not None
        session.rollback()


def test_notification_fails_for_good_once_retries_are_exhausted() -> None:
    """Item "notificação falhada é terminal, sem retry" — confirms the
    other end of the fix: it *does* eventually become FAILED, not retried
    forever. Runs the cycle `_MAX_DELIVERY_ATTEMPTS` times, forcing
    `next_retry_at` into the past between runs instead of sleeping for
    real."""
    from workers.notification_pipeline import _MAX_DELIVERY_ATTEMPTS

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        for attempt in range(1, _MAX_DELIVERY_ATTEMPTS + 1):
            run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)
            assert notification.attempts == attempt
            if attempt < _MAX_DELIVERY_ATTEMPTS:
                assert notification.status == NotificationStatus.PENDING
                # Force the next cycle to pick it up immediately instead of
                # waiting for the real backoff window.
                notification.next_retry_at = None

        assert notification.status == NotificationStatus.FAILED
        session.rollback()


def test_notification_sent_via_email_alone_when_there_is_no_push_subscription(
    monkeypatch: Any,
) -> None:
    """The actual point of item e-mail de alerta: a user with zero push
    subscriptions must still receive the alert, via their account email."""
    import workers.notification_pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "send_email", lambda *args, **kwargs: True)

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.SENT
        assert notification.sent_at is not None
        session.rollback()


def test_notification_sent_via_push_even_when_email_fails(monkeypatch: Any) -> None:
    """Email is an *addition* to push, never a requirement — a successful
    push delivery must still count as SENT even if SES is unconfigured/
    fails, same "sent to at least one channel" contract as before."""
    import workers.notification_pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "webpush", lambda **kwargs: None)
    monkeypatch.setattr(pipeline_module, "send_email", lambda *args, **kwargs: False)

    with session_scope() as session:
        user, alert = _make_user_and_alert(session)
        session.add(
            PushSubscription(
                tenant_id=user.tenant_id,
                user_id=user.id,
                endpoint="https://push.example.com/xyz",
                p256dh="fake-p256dh",
                auth="fake-auth",
            )
        )
        notification = Notification(tenant_id=user.tenant_id, alert_id=alert.id, user_id=user.id)
        session.add(notification)
        session.flush()

        run_notification_delivery_cycle(session, settings=_VAPID_SETTINGS)

        assert notification.status == NotificationStatus.SENT
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


def test_expired_subscription_is_deleted_and_notification_retries(monkeypatch: Any) -> None:
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

        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1

        remaining = session.scalars(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        assert remaining is None
        session.rollback()
