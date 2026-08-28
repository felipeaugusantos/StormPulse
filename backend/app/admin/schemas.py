"""Schemas for the cross-tenant platform-admin panel (FASE 28, ADR-0048)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import UserRole


class AdminUserOut(BaseModel):
    """A user as seen by a platform operator — includes tenant linkage that
    a normal `UserOut` (self-view) has no reason to emphasize."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    is_platform_admin: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int


class AdminTenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    user_count: int
    location_count: int


class AdminTenantListOut(BaseModel):
    items: list[AdminTenantOut]
    total: int


class AdminUserUpdateIn(BaseModel):
    """Partial update — `confirm` mirrors `DeleteAccountIn`'s spirit: no
    accidental one-liner call mutates another tenant's user. At least one
    of `is_active`/`role` must be set (checked in the service layer, since
    "both None" isn't expressible as a Pydantic field constraint here)."""

    is_active: bool | None = None
    role: UserRole | None = None
    confirm: bool = Field(description="Deve ser true para confirmar a mudança")


class AdminAuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_email: str
    action: str
    target_email: str | None
    detail: dict[str, Any]
    created_at: datetime


class AdminAuditLogListOut(BaseModel):
    items: list[AdminAuditLogOut]
    total: int


class AdminRawFrameOut(BaseModel):
    """One raw radar-frame snapshot, exactly as a provider returned it
    (item 4, ADR-0065) — before StormEngine clusters/tracks it into a
    StormCell. `meta.cells` carries the raw per-cell reflectivity list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    weather_source_id: uuid.UUID
    captured_at: datetime
    is_mock: bool
    meta: dict[str, Any]


class AdminRawFrameListOut(BaseModel):
    items: list[AdminRawFrameOut]
    total: int


class AdminStatsOut(BaseModel):
    """Aggregate counters for the platform-admin dashboard (FASE 28 Fase 3,
    ADR-0051). Deliberately simple totals/windows — no per-tenant
    breakdown here, that's what /admin/tenants is for."""

    total_tenants: int
    total_users: int
    active_users_7d: int
    active_users_30d: int
    total_locations: int
    alerts_last_30d: int


class PipelineHealthOut(BaseModel):
    """How fresh each background pipeline's most recent data is (FASE 34
    follow-up — built after a visitor-mode bug report led to manually
    diagnosing a stale satellite cycle over SSH; this surfaces the same
    check in the admin panel instead).

    ``last_updated_at`` is the most recent row's own timestamp, not a
    separate "the cron last fired" log — there's no such log. For
    `storms`/`lightning` it's when our own cycle wrote the row, so a long
    gap can mean either a stuck pipeline or genuinely quiet weather —
    `stale` is a hint worth checking, not a diagnosis. For `satellite` it's
    the GOES scene's own true scan time (STAC item metadata, not our
    cycle's run time) — its `stale` threshold is deliberately looser than
    2x the interval to account for real upstream publish latency (often
    20-40+ minutes on its own), confirmed live rather than assumed.
    """

    name: str
    last_updated_at: datetime | None
    expected_interval_seconds: int
    stale: bool


class PipelineTriggerIn(BaseModel):
    """Which pipeline to run right now — `name` must be one of the keys in
    `app.core.tasks.PIPELINE_TASK_NAMES` (every triggerable pipeline also
    appears in `PipelineHealthOut`, though the reverse isn't required)."""

    name: str


class PipelineTriggerOut(BaseModel):
    queued: bool
    name: str


class AlertVerificationIn(BaseModel):
    """Ground-truth outcome for one already-emitted `Alert` (ADR-0036/0058).

    `confirmed=None` explicitly re-opens/keeps a verification unresolved —
    distinct from `False` (checked, did not happen). `actual_arrival_at`
    only makes sense when `confirmed=True` and the alert had a predicted
    ETA; left `None` otherwise.
    """

    confirmed: bool | None = None
    actual_arrival_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AlertVerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID
    confirmed: bool | None
    actual_arrival_at: datetime | None
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    notes: str | None
    confidence: float | None


class EventTypeMetricsOut(BaseModel):
    """Confirmation-rate metrics for one `AlertEventType`, computed only from
    alerts that already have a resolved (`confirmed` is not None)
    verification — see `ValidationMetricsOut` for why `recall` isn't here."""

    sample_size: int
    confirmed_count: int
    # `None` when `sample_size == 0` — no verified alert of this type yet,
    # not "0% confirmed".
    confirmation_rate: float | None


class ValidationMetricsOut(BaseModel):
    """Real backtesting metrics (ADR-0036/0058) — computed from
    `AlertVerification` rows an operator actually recorded, never
    simulated/fabricated data.

    Only a *confirmation rate* (of alerts StormPulse issued, how many were
    later confirmed true — `engine.validation.precision_recall`'s
    `precision`) is reported, not recall: every row here comes from an
    `Alert` that was already issued, so there is no way yet to observe a
    real event that StormPulse *failed* to alert on (a false negative) —
    reporting a `recall` computed only from issued alerts would silently
    read as 1.0 regardless of how many storms were actually missed, which
    would be a fabricated-looking number, not a measured one.
    """

    sample_size: int
    confirmed_count: int
    confirmation_rate: float | None
    by_event_type: dict[str, EventTypeMetricsOut]
    eta_sample_size: int
    mean_absolute_eta_error_minutes: float | None
    # Below this many resolved verifications, `confirmation_rate` is
    # statistically too noisy to act on (ADR-0036 flagged this gate as
    # needed but left the threshold undefined — set here at 30).
    min_sample_size: int
    reliable: bool
