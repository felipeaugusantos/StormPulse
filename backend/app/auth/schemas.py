"""Auth request/response schemas.

Input schemas are explicit (no mass assignment): only these fields are ever
read from the client, so a caller can never set ``role``, ``tenant_id`` or
``is_active`` on themselves.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)
    # Optional: name of the tenant to create/join. Defaults to a personal tenant.
    tenant_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class GoogleAuthIn(BaseModel):
    # A Google Identity Services ID token (JWT), verified server-side
    # against Google's public keys before any claim is trusted.
    id_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
