"""Schemas for API key management (item 1, ADR-0062)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ApiKeyOut(BaseModel):
    """Never carries the raw key — only what's needed to tell keys apart
    and manage them (list, revoke)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreateOut(ApiKeyOut):
    # The one and only time the raw key is ever readable — the caller must
    # save it now; StormPulse only ever stores its hash from this point on.
    key: str


class ApiKeyListOut(BaseModel):
    items: list[ApiKeyOut]
