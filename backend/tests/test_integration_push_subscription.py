"""Integration tests for the push-subscription endpoints (web push, FASE 22;
Expo push, FASE 26). Needs real Postgres+Redis — auto-skipped otherwise (see
``conftest.py``).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def test_register_and_delete_web_push_subscription(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    endpoint = f"https://push.example.com/{uuid.uuid4().hex}"

    resp = await client.post(
        "/api/v1/users/me/push-subscription",
        json={"endpoint": endpoint, "keys": {"p256dh": "fake-p256dh", "auth": "fake-auth"}},
        headers=headers,
    )
    assert resp.status_code == 204

    resp = await client.request(
        "DELETE",
        "/api/v1/users/me/push-subscription",
        json={"endpoint": endpoint},
        headers=headers,
    )
    assert resp.status_code == 204


async def test_register_and_delete_expo_push_token(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"

    resp = await client.post(
        "/api/v1/users/me/push-subscription/expo",
        json={"expo_push_token": token},
        headers=headers,
    )
    assert resp.status_code == 204

    resp = await client.request(
        "DELETE",
        "/api/v1/users/me/push-subscription/expo",
        json={"expo_push_token": token},
        headers=headers,
    )
    assert resp.status_code == 204


async def test_registering_the_same_expo_token_twice_is_idempotent(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    token = f"ExponentPushToken[{uuid.uuid4().hex}]"

    for _ in range(2):
        resp = await client.post(
            "/api/v1/users/me/push-subscription/expo",
            json={"expo_push_token": token},
            headers=headers,
        )
        assert resp.status_code == 204
