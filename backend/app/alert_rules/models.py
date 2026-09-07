"""Custom alert rules — data model (Fase 3 — Alertas Personalizados,
ADR-0086).

Eight tenant-scoped tables, additive alongside the existing `Alert`/
`Notification`/`AlertPreference` (never touched by this module) — see
ADR-0086 for why this is a parallel system, not a refactor of the storm
engine's own alerting:

- ``AlertRule`` — one user-defined rule for one location: name, on/off,
  lead time, quiet hours, cooldown.
- ``AlertCondition`` — belongs to a rule; DNF evaluation via ``group_index``
  (same group = AND, different groups = OR — see
  ``engine/alert_rules.py``).
- ``AlertChannel`` — a configured delivery channel instance (email reuses
  the user's own address, push reuses existing subscriptions, webhook has
  its own URL+secret, WhatsApp/SMS are abstractions — see
  ``app/alert_rules/providers.py``).
- ``AlertRecipient`` — who gets notified, through which channel, for which
  rule.
- ``AlertEvent`` — one firing episode of a rule, with its own lifecycle
  (open → updated → closed) — optionally bridges to a normal ``Alert`` row
  so it shows up in the existing ``/alerts`` feed too.
- ``AlertDelivery`` — one row per (event, recipient) delivery attempt —
  unlike ``Notification`` (one row covering every channel at once), this
  is per-channel so retries/escalation can be tracked independently.
- ``AlertAcknowledgement`` — 1:1 with an event (first ack wins), distinct
  from ``AlertVerification`` (ground-truth of what happened, not "did the
  user see this").
- ``AlertEscalation`` — ordered steps of "if not acked within N minutes,
  also notify recipient X", attached to a rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AlertEventStatus, NotificationChannel, NotificationStatus
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AlertRule(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # How far ahead of the matched condition to warn, when the underlying
    # metric is itself a forecast (e.g. "wind > 40km/h in the next
    # lead_time_minutes"), not just the value right now. 0 = evaluate the
    # current/nearest-term value only.
    lead_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Denormalized from the newest AlertEvent for this rule — read by
    # engine.alert_rules.is_in_cooldown without a join on every evaluation
    # cycle (this table is read once per rule per cycle; the events table
    # would need an extra query otherwise).
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertCondition(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_conditions"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # One of engine.alert_rules.Metric — free text, not a DB enum: the
    # metric catalog is expected to grow, and a native enum would need a
    # migration per addition (see ADR on AlertEventType enum churn).
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    operator: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    # Same group = AND together; different groups = OR across groups (DNF —
    # see engine/alert_rules.py::evaluate_conditions).
    group_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AlertChannel(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_channels"

    kind: Mapped[NotificationChannel] = mapped_column(
        SqlEnum(NotificationChannel, name="notification_channel", native_enum=True), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # WEBHOOK only.
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # AES-256-GCM ciphertext (app.core.crypto.encrypt_field) — never stored
    # in plain text, same treatment as other at-rest secrets in this
    # codebase. Never searched/filtered on, so no blind index needed.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WHATSAPP/SMS abstraction only — see app/alert_rules/providers.py for
    # why there's no real send behind this yet.
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AlertRecipient(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_recipients"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The account holder by default; nullable so a channel can target
    # someone outside the account too (e.g. a webhook has no "user" at
    # all — the URL itself is the destination).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AlertEvent(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_events"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Bridge to the existing /alerts feed — SET NULL (not CASCADE) so
    # deleting the bridge Alert (there's no such admin action today, but if
    # one is ever added) never takes the audit trail of this event with it.
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[AlertEventStatus] = mapped_column(
        SqlEnum(AlertEventStatus, name="alert_event_status", native_enum=True),
        nullable=False,
        default=AlertEventStatus.OPEN,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # JSON-serialized engine.alert_rules.MetricSnapshot at the moment this
    # transition happened — same "opaque text, only ever re-parsed by our
    # own code" pattern as Location.boundary_geojson.
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class AlertDelivery(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_deliveries"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_recipients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which of the event's transitions this delivery is for — an event
    # open→updated→closed produces up to three separate delivery batches,
    # one per recipient each time.
    notice_kind: Mapped[AlertEventStatus] = mapped_column(
        SqlEnum(AlertEventStatus, name="alert_event_status", native_enum=True), nullable=False
    )
    # Denormalized from recipient.channel.kind — avoids a join for the
    # delivery worker's hot path (find PENDING deliveries to attempt).
    channel_kind: Mapped[NotificationChannel] = mapped_column(
        SqlEnum(NotificationChannel, name="notification_channel", native_enum=True), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SqlEnum(NotificationStatus, name="notification_status", native_enum=True),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AlertAcknowledgement(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Distinct from `AlertVerification` (ground-truth of what actually
    happened, dev/operator-only) — this is "did a user see this and say
    so", the signal escalation waits on."""

    __tablename__ = "alert_acknowledgements"
    __table_args__ = (UniqueConstraint("event_id", name="uq_alert_ack_event"),)

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    acknowledged_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AlertEscalation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_escalations"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Ordered steps — step 0 fires first if the event is still unacked
    # after its own delay_minutes, step 1 after that, etc.
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_recipients.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
