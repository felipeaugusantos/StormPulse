"""Notification model — delivery record for an alert, and the push
registrations (browser Web Push, FASE 22; mobile Expo push, FASE 26) those
deliveries fan out to."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import NotificationChannel, NotificationStatus
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel", native_enum=True),
        nullable=False,
        default=NotificationChannel.PUSH,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status", native_enum=True),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class PushSubscription(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A device's push registration — either a browser's Web Push
    subscription (``PushManager.subscribe()``, FASE 22) or the mobile app's
    Expo push token (FASE 26). ``platform`` picks which pair of columns is
    populated; the delivery pipeline branches on it (``pywebpush`` for
    "web", Expo's push API for "expo") rather than guessing from which
    columns happen to be set."""

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    # Web Push (platform="web") — all three always set together.
    endpoint: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    p256dh: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Expo push (platform="expo") — one opaque token per device.
    expo_push_token: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
