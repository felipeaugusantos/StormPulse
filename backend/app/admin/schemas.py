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
    """Which pipeline to run right now — `name` must be one of the values
    `PipelineHealthOut.name` reports (`app.core.tasks.PIPELINE_TASK_NAMES`)."""

    name: str


class PipelineTriggerOut(BaseModel):
    queued: bool
    name: str
