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
    created_at: datetime


class DeleteAccountIn(BaseModel):
    """Simple confirmation gate — no accidental one-liner call deletes an account."""

    confirm: bool = Field(description="Deve ser true para confirmar a exclusão permanente")
