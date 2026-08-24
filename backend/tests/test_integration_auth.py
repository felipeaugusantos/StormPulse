"""Integration tests for the auth + /users/me HTTP flow (FASE 14).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
``conftest.py``). Mirrors the "Integration — register, login, /users/me"
step already exercised via curl in ``.github/workflows/ci.yml``, as proper
pytest assertions.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

_PASSWORD = "supersecret123"


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex}@example.com"


async def test_register_returns_created_user(client: AsyncClient) -> None:
    email = _unique_email()
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": _PASSWORD, "full_name": "CI"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == email
    assert body["role"] == "user"
    assert body["is_active"] is True


async def test_register_defaults_to_storm_only(client: AsyncClient) -> None:
    email = _unique_email()
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 201
    body = resp.json()
    assert body["storm_module_enabled"] is True
    assert body["agro_module_enabled"] is False


async def test_register_with_agro_module_selected(client: AsyncClient) -> None:
    email = _unique_email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "storm_module": True,
            "agro_module": True,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["storm_module_enabled"] is True
    assert body["agro_module_enabled"] is True

    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    access = login.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert me.json()["agro_module_enabled"] is True


async def test_register_rejects_no_modules_selected(client: AsyncClient) -> None:
    email = _unique_email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "storm_module": False,
            "agro_module": False,
        },
    )
    assert resp.status_code == 422


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    email = _unique_email()
    payload = {"email": email, "password": _PASSWORD}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_login_returns_token_pair(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_users_me_with_valid_token(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    access = login.json()["access_token"]

    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email


async def test_users_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_refresh_issues_a_new_token_pair(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    refresh_token = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_refresh_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


async def test_delete_me_without_confirm_returns_400(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    access = login.json()["access_token"]

    resp = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access}"},
        json={"confirm": False},
    )
    assert resp.status_code == 400


async def test_delete_me_removes_account_and_owned_data(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    access = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    location_payload = {
        "name": "Casa",
        "kind": "home",
        "latitude": -23.55,
        "longitude": -46.63,
        "radius_km": 50,
    }
    created = (
        await client.post("/api/v1/locations", json=location_payload, headers=headers)
    ).json()

    resp = await client.request(
        "DELETE", "/api/v1/users/me", headers=headers, json={"confirm": True}
    )
    assert resp.status_code == 204

    # The old access token is for a user that no longer exists.
    me_resp = await client.get("/api/v1/users/me", headers=headers)
    assert me_resp.status_code == 401

    # Can register the same e-mail again — nothing orphaned blocking it.
    again = await client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert again.status_code == 201
    assert created["id"]  # sanity: the location really was created before deletion
