"""Custom alert rule schemas (Fase 3 — Alertas Personalizados, ADR-0086)."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import AlertEventStatus, NotificationChannel
from engine.alert_rules import Metric, Operator

_VALID_METRICS = set(get_args(Metric))
_VALID_OPERATORS = set(get_args(Operator))


class AlertConditionIn(BaseModel):
    metric: str
    operator: str
    threshold: float
    group: int = 0

    @field_validator("metric")
    @classmethod
    def _validate_metric(cls, value: str) -> str:
        if value not in _VALID_METRICS:
            raise ValueError(f"metric precisa ser um de: {', '.join(sorted(_VALID_METRICS))}")
        return value

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, value: str) -> str:
        if value not in _VALID_OPERATORS:
            raise ValueError(f"operator precisa ser um de: {', '.join(sorted(_VALID_OPERATORS))}")
        return value


class AlertConditionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    metric: str
    operator: str
    threshold: float
    group: int


class AlertRuleCreate(BaseModel):
    location_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    lead_time_minutes: int = Field(default=0, ge=0)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    cooldown_minutes: int = Field(default=0, ge=0)
    conditions: list[AlertConditionIn] = Field(min_length=1)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    lead_time_minutes: int | None = Field(default=None, ge=0)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0)
    # Omitted (None) leaves existing conditions untouched; an explicit
    # (possibly empty-of-changes) list replaces them all atomically — same
    # "replace, don't patch piecemeal" contract as
    # LocationUpdate.alert_preferences.
    conditions: list[AlertConditionIn] | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    name: str
    enabled: bool
    lead_time_minutes: int
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    cooldown_minutes: int
    last_fired_at: datetime | None
    conditions: list[AlertConditionOut]


class AlertChannelIn(BaseModel):
    kind: NotificationChannel
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    webhook_url: str | None = None
    # Plain text in the request — encrypted at rest before it ever touches
    # the DB (app.core.crypto.encrypt_field), never echoed back in
    # AlertChannelOut.
    webhook_secret: str | None = None
    phone_number: str | None = None


class AlertChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: NotificationChannel
    name: str
    enabled: bool
    webhook_url: str | None
    phone_number: str | None
    has_webhook_secret: bool = False


class AlertRecipientIn(BaseModel):
    channel_id: uuid.UUID
    user_id: uuid.UUID | None = None
    enabled: bool = True


class AlertRecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    user_id: uuid.UUID | None
    enabled: bool


class AlertEscalationIn(BaseModel):
    step_order: int = Field(default=0, ge=0)
    delay_minutes: int = Field(gt=0)
    recipient_id: uuid.UUID
    enabled: bool = True


class AlertEscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_order: int
    delay_minutes: int
    recipient_id: uuid.UUID
    enabled: bool


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    location_id: uuid.UUID
    alert_id: uuid.UUID | None
    status: AlertEventStatus
    opened_at: datetime
    last_updated_at: datetime
    closed_at: datetime | None
    acknowledged: bool = False


class AcknowledgeIn(BaseModel):
    notes: str | None = None


class SimulateResult(BaseModel):
    """Fase 3 acceptance criterion: a simulation never writes an
    AlertEvent/AlertDelivery/Alert — this is the entire response, nothing
    persisted."""

    would_fire: bool
    snapshot: dict[str, float | None]
    matched_groups: list[int]
