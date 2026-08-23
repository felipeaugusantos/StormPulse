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
