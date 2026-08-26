"""Integration tests for API key management and the external/public API
(item 1, ADR-0062) — real Postgres, real HTTP, never a mocked DB.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration


async def _create_key(
    client: AsyncClient, headers: dict[str, str], name: str = "CI key"
) -> dict[str, Any]:
    resp = await client.post("/api/v1/users/me/api-keys", json={"name": name}, headers=headers)
    assert resp.status_code == 201
    body: dict[str, Any] = resp.json()
    return body


async def test_create_list_and_revoke_api_key(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = await _create_key(client, headers)
    assert created["key"].startswith("sp_live_")
    assert created["key_prefix"] == created["key"][: len(created["key_prefix"])]
    assert created["revoked_at"] is None

    listed = await client.get("/api/v1/users/me/api-keys", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert "key" not in items[0]  # the raw value is never listed again
    assert items[0]["id"] == created["id"]

    revoke = await client.delete(f"/api/v1/users/me/api-keys/{created['id']}", headers=headers)
    assert revoke.status_code == 204

    listed_again = await client.get("/api/v1/users/me/api-keys", headers=headers)
    assert listed_again.json()["items"][0]["revoked_at"] is not None


async def test_revoke_unknown_key_returns_404(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.delete(f"/api/v1/users/me/api-keys/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


async def test_external_api_requires_a_key(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/external/v1/locations")
    assert resp.status_code == 401


async def test_external_api_rejects_an_unknown_key(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/external/v1/locations", headers={"X-API-Key": "sp_live_not-a-real-key"}
    )
    assert resp.status_code == 401


async def test_external_api_rejects_a_revoked_key(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = await _create_key(client, headers)
    await client.delete(f"/api/v1/users/me/api-keys/{created['id']}", headers=headers)

    resp = await client.get("/api/v1/external/v1/locations", headers={"X-API-Key": created["key"]})
    assert resp.status_code == 401


async def test_external_api_lists_only_the_keys_own_tenant_locations(
    client: AsyncClient,
) -> None:
    token_a = await register_and_login(client)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    key_a = await _create_key(client, headers_a)

    await client.post(
        "/api/v1/locations",
        json={"name": "Fazenda A", "kind": "farm", "latitude": -23.5, "longitude": -46.6},
        headers=headers_a,
    )

    token_b = await register_and_login(client)
    headers_b = {"Authorization": f"Bearer {token_b}"}
    await client.post(
        "/api/v1/locations",
        json={"name": "Fazenda B", "kind": "farm", "latitude": -22.9, "longitude": -43.2},
        headers=headers_b,
    )

    resp = await client.get("/api/v1/external/v1/locations", headers={"X-API-Key": key_a["key"]})
    assert resp.status_code == 200
    names = [loc["name"] for loc in resp.json()]
    assert names == ["Fazenda A"]


async def test_external_api_risk_returns_404_when_none_computed_yet(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    key = await _create_key(client, headers)

    loc = await client.post(
        "/api/v1/locations",
        json={"name": "Casa", "kind": "home", "latitude": -23.5, "longitude": -46.6},
        headers=headers,
    )
    location_id = loc.json()["id"]

    resp = await client.get(
        f"/api/v1/external/v1/locations/{location_id}/risk",
        headers={"X-API-Key": key["key"]},
    )
    assert resp.status_code == 404


async def test_external_api_risk_404_for_a_location_the_key_does_not_own(
    client: AsyncClient,
) -> None:
    token_owner = await register_and_login(client)
    headers_owner = {"Authorization": f"Bearer {token_owner}"}
    loc = await client.post(
        "/api/v1/locations",
        json={"name": "Casa", "kind": "home", "latitude": -23.5, "longitude": -46.6},
        headers=headers_owner,
    )
    location_id = loc.json()["id"]

    token_other = await register_and_login(client)
    headers_other = {"Authorization": f"Bearer {token_other}"}
    key_other = await _create_key(client, headers_other)

    resp = await client.get(
        f"/api/v1/external/v1/locations/{location_id}/risk",
        headers={"X-API-Key": key_other["key"]},
    )
    assert resp.status_code == 404


async def test_external_api_lists_alerts(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    key = await _create_key(client, headers)

    resp = await client.get("/api/v1/external/v1/alerts", headers={"X-API-Key": key["key"]})
    assert resp.status_code == 200
    assert resp.json() == []
