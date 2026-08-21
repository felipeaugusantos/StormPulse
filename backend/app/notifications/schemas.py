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


class ExpoPushTokenIn(BaseModel):
    """The mobile app's Expo push token (FASE 26) — ``ExponentPushToken[...]``,
    obtained from ``expo-notifications``' ``getExpoPushTokenAsync()``."""

    expo_push_token: str = Field(min_length=1)


class ExpoPushTokenDeleteIn(BaseModel):
    expo_push_token: str = Field(min_length=1)
