"""User-facing Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.enums import UserRole


class UserOut(BaseModel):
    """Public representation of a user (never exposes the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    is_platform_admin: bool
    created_at: datetime
    # Module selection (FASE 30) — which modules the user's tenant has
    # access to, chosen at registration. Drives which tabs the frontend
    # shows; not on the ``User`` row itself (it's a tenant-level setting),
    # so ``read_me`` builds this field-by-field rather than relying on
    # ``from_attributes`` alone.
    storm_module_enabled: bool
    agro_module_enabled: bool
    # FASE 8 (ADR-0059) — informational only, never gates login (see
    # `User.email_verified`'s own docstring). Drives a "confirme seu
    # e-mail" banner in the frontend, nothing more.
    email_verified: bool


class DeleteAccountIn(BaseModel):
    """Simple confirmation gate — no accidental one-liner call deletes an account."""

    confirm: bool = Field(description="Deve ser true para confirmar a exclusão permanente")
