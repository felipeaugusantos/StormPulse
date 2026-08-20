"""Push subscription schemas — the shape the browser's ``PushManager.subscribe()``
result already comes in (``PushSubscriptionJSON``), FASE 22."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1)
    keys: PushSubscriptionKeys


class PushSubscriptionDeleteIn(BaseModel):
    endpoint: str = Field(min_length=1)
