from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.enums import UserRole

TEAM_ROLES = {
    UserRole.OWNER,
    UserRole.ADMIN,
    UserRole.AGRONOMIST,
    UserRole.OPERATOR,
    UserRole.VIEWER,
}


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    organization_wide_access: bool
    access_expires_at: datetime | None
    created_at: datetime


class InvitationCreateIn(BaseModel):
    email: EmailStr
    role: UserRole
    location_id: uuid.UUID | None = None
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    access_expires_at: datetime | None = None

    @model_validator(mode="after")
    def valid_role(self) -> InvitationCreateIn:
        if self.role not in TEAM_ROLES or self.role == UserRole.OWNER:
            raise ValueError("Convites aceitam administrador, agrônomo, operador ou visualizador")
        return self


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    role: str
    location_id: uuid.UUID | None
    expires_at: datetime
    access_expires_at: datetime | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationAcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=300)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class MemberUpdateIn(BaseModel):
    role: UserRole | None = None
    organization_wide_access: bool | None = None
    location_ids: list[uuid.UUID] | None = None
    access_expires_at: datetime | None = None

    @model_validator(mode="after")
    def has_change(self) -> MemberUpdateIn:
        if not self.model_fields_set:
            raise ValueError("Informe ao menos uma alteração")
        if self.role is not None and (self.role not in TEAM_ROLES or self.role == UserRole.OWNER):
            raise ValueError("O papel proprietário não pode ser atribuído por esta operação")
        return self


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    target_user_id: uuid.UUID | None
    action: str
    location_id: uuid.UUID | None
    detail_json: str
    created_at: datetime
