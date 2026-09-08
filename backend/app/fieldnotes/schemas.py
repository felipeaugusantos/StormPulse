"""Caderno de Campo API schemas (Fase 6, ADR-0090).

Every `*Create` schema accepts an optional client-supplied `id` (the
mobile app's offline-generated UUID — see `models.py` module docstring);
omitted, the server generates one, exactly like every other resource in
the project. Every `*Update` schema requires `base_version`: the version
the client last saw, checked against the row's current `version` before
applying the write (409 on mismatch, see `router.py`) — never a silent
overwrite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import FieldOccurrenceStatus, FieldTaskStatus


class FieldOccurrenceCreate(BaseModel):
    id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None
    recommended_action_id: uuid.UUID | None = None
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1)
    latitude: float
    longitude: float
    reported_at: datetime | None = None


class FieldOccurrenceUpdate(BaseModel):
    base_version: int
    status: FieldOccurrenceStatus | None = None
    description: str | None = None


class FieldOccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    alert_id: uuid.UUID | None
    recommended_action_id: uuid.UUID | None
    category: str
    description: str
    latitude: float
    longitude: float
    status: FieldOccurrenceStatus
    reported_by: uuid.UUID
    reported_at: datetime
    version: int


class InspectionCreate(BaseModel):
    id: uuid.UUID | None = None
    occurrence_id: uuid.UUID | None = None
    notes: str = Field(min_length=1)
    latitude: float | None = None
    longitude: float | None = None
    inspected_at: datetime | None = None


class InspectionUpdate(BaseModel):
    base_version: int
    notes: str | None = None


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    occurrence_id: uuid.UUID | None
    notes: str
    latitude: float | None
    longitude: float | None
    inspected_by: uuid.UUID
    inspected_at: datetime
    version: int


class PhotoOut(BaseModel):
    id: uuid.UUID
    inspection_id: uuid.UUID
    content_type: str
    size_bytes: int
    uploaded_by: uuid.UUID
    uploaded_at: datetime
    # Short-lived signed URL, generated at read time — never a public/
    # permanent object URL (ADR-0090).
    url: str


class TaskCreate(BaseModel):
    id: uuid.UUID | None = None
    occurrence_id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None
    recommended_action_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=160)
    description: str | None = None
    assigned_to: uuid.UUID | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    base_version: int
    title: str | None = None
    description: str | None = None
    assigned_to: uuid.UUID | None = None
    due_at: datetime | None = None
    status: FieldTaskStatus | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    occurrence_id: uuid.UUID | None
    alert_id: uuid.UUID | None
    recommended_action_id: uuid.UUID | None
    title: str
    description: str | None
    assigned_to: uuid.UUID | None
    due_at: datetime | None
    status: FieldTaskStatus
    completed_by: uuid.UUID | None
    completed_at: datetime | None
    version: int


class TimelineEntry(BaseModel):
    """One chronological entry in a talhão's field-notebook timeline —
    `kind` tags which underlying record `ref_id` points to (never a
    second, separate source of truth: the client fetches the full record
    from its own endpoint if it needs more than this summary)."""

    kind: str  # "occurrence" | "inspection" | "task" | "alert"
    ref_id: uuid.UUID
    occurred_at: datetime
    title: str
    summary: str
