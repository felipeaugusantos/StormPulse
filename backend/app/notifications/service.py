"""Push subscription CRUD (FASE 22)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import PushSubscription
from app.notifications.schemas import PushSubscriptionIn
from app.users.models import User

_WEB_PLATFORM = "web"
_EXPO_PLATFORM = "expo"


async def upsert_subscription(
    session: AsyncSession, user: User, data: PushSubscriptionIn
) -> PushSubscription:
    """Register (or refresh the keys of) a subscription for this endpoint.

    ``endpoint`` is globally unique — a browser calling ``subscribe()``
    again for the same registration returns the same endpoint, so this is
    naturally idempotent across repeat opt-ins from the same device.
    """
    result = await session.execute(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.user_id = user.id
        existing.tenant_id = user.tenant_id
        existing.p256dh = data.keys.p256dh
        existing.auth = data.keys.auth
        await session.commit()
        return existing

    subscription = PushSubscription(
        tenant_id=user.tenant_id,
        user_id=user.id,
        platform=_WEB_PLATFORM,
        endpoint=data.endpoint,
        p256dh=data.keys.p256dh,
        auth=data.keys.auth,
    )
    session.add(subscription)
    await session.commit()
    return subscription


async def delete_subscription(session: AsyncSession, user: User, endpoint: str) -> None:
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    await session.commit()


async def upsert_expo_token(
    session: AsyncSession, user: User, expo_push_token: str
) -> PushSubscription:
    """Register (or re-associate) a mobile device's Expo push token
    (FASE 26) — same idempotency reasoning as ``upsert_subscription``: the
    token is stable per device/app-install, so re-registering it is a
    normal occurrence (app reopen, token refresh), not an error."""
    result = await session.execute(
        select(PushSubscription).where(PushSubscription.expo_push_token == expo_push_token)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.user_id = user.id
        existing.tenant_id = user.tenant_id
        await session.commit()
        return existing

    subscription = PushSubscription(
        tenant_id=user.tenant_id,
        user_id=user.id,
        platform=_EXPO_PLATFORM,
        expo_push_token=expo_push_token,
    )
    session.add(subscription)
    await session.commit()
    return subscription


async def delete_expo_token(session: AsyncSession, user: User, expo_push_token: str) -> None:
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.expo_push_token == expo_push_token,
            PushSubscription.user_id == user.id,
        )
    )
    await session.commit()
