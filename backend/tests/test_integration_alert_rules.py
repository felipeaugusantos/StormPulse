"""Integration tests for the alert-rules CRUD + simulate endpoints (Fase 3
— Alertas Personalizados, ADR-0086).

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

_LOCATION_PAYLOAD = {
    "name": "Fazenda (teste alert-rules)",
    "kind": "farm",
    "latitude": -21.1775,
    "longitude": -47.8103,
    "radius_km": 50,
}


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_location(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post("/api/v1/locations", json=_LOCATION_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    return str(resp.json()["id"])


async def test_create_rule_returns_the_conditions_back(client: AsyncClient) -> None:
    """Regression test: the post-commit re-fetch of conditions needs
    set_tenant_context re-applied (RLS transaction-scoped GUC is reset by
    commit) — without that fix this silently comes back empty."""
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Vento forte",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
        },
        headers=headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert len(body["conditions"]) == 1
    assert body["conditions"][0]["metric"] == "wind_kmh"


async def test_create_rule_rejects_unknown_metric(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Regra inválida",
            "conditions": [{"metric": "moon_phase", "operator": ">", "threshold": 1.0}],
        },
        headers=headers,
    )

    assert resp.status_code == 422


async def test_create_rule_for_someone_elses_location_404s(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    location_id = await _create_location(client, owner_headers)

    other_headers = await _auth_headers(client)
    resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Não é meu local",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
        },
        headers=other_headers,
    )

    assert resp.status_code == 404


async def test_update_replaces_conditions_atomically(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    create_resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Regra",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
        },
        headers=headers,
    )
    rule_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/alert-rules/{rule_id}",
        json={
            "conditions": [
                {"metric": "rain_mm", "operator": ">", "threshold": 20.0},
                {"metric": "wind_kmh", "operator": ">", "threshold": 60.0, "group": 1},
            ]
        },
        headers=headers,
    )

    assert update_resp.status_code == 200
    conditions = update_resp.json()["conditions"]
    assert len(conditions) == 2
    assert {c["metric"] for c in conditions} == {"rain_mm", "wind_kmh"}


async def test_update_omitting_conditions_leaves_them_untouched(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    create_resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Regra",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
        },
        headers=headers,
    )
    rule_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/alert-rules/{rule_id}", json={"name": "Regra renomeada"}, headers=headers
    )

    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["name"] == "Regra renomeada"
    assert len(body["conditions"]) == 1


async def test_simulate_never_persists_an_event_or_delivery(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    create_resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Regra",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": -1.0}],
        },
        headers=headers,
    )
    rule_id = create_resp.json()["id"]

    sim_resp = await client.post(f"/api/v1/alert-rules/{rule_id}/simulate", headers=headers)

    assert sim_resp.status_code == 200
    body = sim_resp.json()
    assert body["would_fire"] is True  # any real wind is > -1
    assert "snapshot" in body

    events_resp = await client.get(f"/api/v1/alert-rules/{rule_id}/events", headers=headers)
    assert events_resp.json() == []


async def test_delete_rule_removes_it_from_the_list(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    create_resp = await client.post(
        "/api/v1/alert-rules",
        json={
            "location_id": location_id,
            "name": "Regra a apagar",
            "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
        },
        headers=headers,
    )
    rule_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/alert-rules/{rule_id}", headers=headers)
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/alert-rules/{rule_id}", headers=headers)
    assert get_resp.status_code == 404


async def test_channel_never_echoes_the_webhook_secret(client: AsyncClient) -> None:
    headers = await _auth_headers(client)

    resp = await client.post(
        "/api/v1/alert-channels",
        json={
            "kind": "webhook",
            "name": "Webhook externo",
            "webhook_url": "https://example.com/hook",
            "webhook_secret": "super-secreto",
        },
        headers=headers,
    )

    assert resp.status_code == 201
    body = resp.json()
    assert "webhook_secret" not in body
    assert body["has_webhook_secret"] is True


async def test_recipients_and_escalations_are_scoped_to_the_rules_tenant(
    client: AsyncClient,
) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    rule_id = (
        await client.post(
            "/api/v1/alert-rules",
            json={
                "location_id": location_id,
                "name": "Regra",
                "conditions": [{"metric": "wind_kmh", "operator": ">", "threshold": 40.0}],
            },
            headers=headers,
        )
    ).json()["id"]
    channel_id = (
        await client.post(
            "/api/v1/alert-channels",
            json={"kind": "email", "name": "E-mail"},
            headers=headers,
        )
    ).json()["id"]

    recipient_resp = await client.post(
        f"/api/v1/alert-rules/{rule_id}/recipients",
        json={"channel_id": channel_id},
        headers=headers,
    )
    assert recipient_resp.status_code == 201
    recipient_id = recipient_resp.json()["id"]

    escalation_resp = await client.post(
        f"/api/v1/alert-rules/{rule_id}/escalations",
        json={"delay_minutes": 10, "recipient_id": recipient_id},
        headers=headers,
    )
    assert escalation_resp.status_code == 201

    other_headers = await _auth_headers(client)
    other_recipient_resp = await client.post(
        f"/api/v1/alert-rules/{rule_id}/recipients",
        json={"channel_id": channel_id},
        headers=other_headers,
    )
    # The rule itself isn't the other tenant's — 404 before the channel is
    # ever consulted.
    assert other_recipient_resp.status_code == 404


async def test_nonexistent_rule_returns_404_everywhere(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    fake_id = uuid.uuid4()

    assert (await client.get(f"/api/v1/alert-rules/{fake_id}", headers=headers)).status_code == 404
    assert (
        await client.post(f"/api/v1/alert-rules/{fake_id}/simulate", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/alert-rules/{fake_id}", headers=headers)
    ).status_code == 404
