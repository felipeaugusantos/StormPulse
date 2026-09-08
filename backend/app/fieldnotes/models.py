"""Caderno de Campo — data model (Fase 6, ADR-0090).

Four tenant-scoped tables relating alerts/recommendations to what actually
happened in the field: `FieldOccurrence` (something noticed), `Inspection`
(a visit, with notes/coordinate/photos), `Task` (an assignable follow-up
with a deadline), `Photo` (an inspection's attachment, stored in the
private MinIO/S3-compatible bucket — see `app/fieldnotes/storage.py`,
never a public URL).

**Offline-first identity.** Every row's `id` can be supplied by the
caller at creation (`UUIDPrimaryKeyMixin.id` only defaults to
`uuid.uuid4()` when not set) — the mobile app generates it on-device while
offline, so replaying a queued create after reconnecting is naturally
idempotent (same id twice is the same record, not a duplicate).

**Conflict detection, not silent overwrite.** `version` starts at 1 and
increments on every update. A client sends the `base_version` it last
saw; the router (not this module) compares it against the current row and
returns 409 instead of applying the write when they differ — never a
last-write-wins merge.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FieldOccurrenceStatus, FieldTaskStatus
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class FieldOccurrence(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Something noticed in the field — the entry point of the notebook.
    Optionally traces back to the signal that prompted it (`alert_id`/
    `recommended_action_id`), but standing on its own is also valid (a
    producer can log something the system never flagged)."""

    __tablename__ = "field_occurrences"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommended_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommended_actions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[FieldOccurrenceStatus] = mapped_column(
        SqlEnum(FieldOccurrenceStatus, name="field_occurrence_status", native_enum=True),
        nullable=False,
        default=FieldOccurrenceStatus.OPEN,
    )
    reported_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Inspection(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A field visit — notes, an optional coordinate, and (via `Photo`)
    optional attachments. Belongs to one talhão; may or may not be tied to
    a specific occurrence (a routine inspection has none)."""

    __tablename__ = "field_inspections"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_occurrences.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    inspected_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Task(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """An assignable follow-up with a deadline — the "what to do about
    it" half of the notebook. `assigned_to`/`completed_by` are SET NULL
    (not CASCADE): a user leaving the tenant must never delete the task
    history, only its author reference."""

    __tablename__ = "field_tasks"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_occurrences.id", ondelete="SET NULL"), nullable=True, index=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommended_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommended_actions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[FieldTaskStatus] = mapped_column(
        SqlEnum(FieldTaskStatus, name="field_task_status", native_enum=True),
        nullable=False,
        default=FieldTaskStatus.PENDING,
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Photo(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """One inspection attachment — the bytes live in the private object
    store (`object_key`), never in this table and never public. `Inspection`
    deletion cascades: a photo with no inspection to belong to is orphaned
    data, not a record worth keeping."""

    __tablename__ = "field_photos"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
