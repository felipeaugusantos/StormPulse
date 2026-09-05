from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.organizations import service

pytestmark = pytest.mark.integration
PASSWORD = "supersecret123"
FARM = {
    "name": "Fazenda Equipe",
    "kind": "farm",
    "latitude": -21.1,
    "longitude": -47.8,
    "radius_km": 20,
    "alert_preferences": [],
}


async def _owner(client: AsyncClient) -> dict[str, str]:
    email = f"owner-{uuid.uuid4().hex}@example.com"
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD, "accept_terms": True}
    )
    assert response.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _invite_and_accept(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    owner: dict[str, str],
    farm_id: str,
    role: str,
) -> tuple[dict[str, str], str]:
    token = f"token-{uuid.uuid4().hex}"
    monkeypatch.setattr(service, "generate_invitation_token", lambda: token)
    email = f"{role}-{uuid.uuid4().hex}@example.com"
    invited = await client.post(
        "/api/v1/organizations/current/invitations",
        headers=owner,
        json={"email": email, "role": role, "location_id": farm_id},
    )
    assert invited.status_code == 201
    accepted = await client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": token, "password": PASSWORD, "full_name": role},
    )
    assert accepted.status_code == 201
    reused = await client.post(
        "/api/v1/organizations/invitations/accept", json={"token": token, "password": PASSWORD}
    )
    assert reused.status_code == 410
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, accepted.json()["id"]


async def test_scopes_roles_reuse_isolation_and_immediate_revocation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await _owner(client)
    assert (await client.get("/api/v1/organizations/current", headers=owner)).status_code == 200
    farm = (await client.post("/api/v1/locations", headers=owner, json=FARM)).json()
    sibling_farm = (
        await client.post(
            "/api/v1/locations", headers=owner, json={**FARM, "name": "Fazenda Restrita"}
        )
    ).json()
    viewer, viewer_id = await _invite_and_accept(client, monkeypatch, owner, farm["id"], "viewer")
    assert (await client.get("/api/v1/locations", headers=viewer)).json()[0]["id"] == farm["id"]
    assert (
        await client.put(
            f"/api/v1/locations/{farm['id']}", headers=viewer, json={"name": "proibido"}
        )
    ).status_code == 403
    assert (
        await client.get("/api/v1/organizations/current/members", headers=viewer)
    ).status_code == 403

    operator, operator_id = await _invite_and_accept(
        client, monkeypatch, owner, farm["id"], "operator"
    )
    assert (
        await client.put(
            f"/api/v1/locations/{farm['id']}", headers=operator, json={"name": "Atualizada"}
        )
    ).status_code == 200
    assert (
        await client.get("/api/v1/organizations/current/members", headers=operator)
    ).status_code == 403
    changed_operator = await client.patch(
        f"/api/v1/organizations/current/members/{operator_id}",
        headers=owner,
        json={
            "role": "viewer",
            "organization_wide_access": False,
            "location_ids": [farm["id"]],
        },
    )
    assert changed_operator.status_code == 200
    assert changed_operator.json()["role"] == "viewer"
    assert (
        await client.put(
            f"/api/v1/locations/{farm['id']}",
            headers=operator,
            json={"name": "Agora proibida"},
        )
    ).status_code == 403

    agronomist, _ = await _invite_and_accept(client, monkeypatch, owner, farm["id"], "agronomist")
    assert (
        await client.put(
            f"/api/v1/locations/{farm['id']}",
            headers=agronomist,
            json={"name": "Fazenda Agronômica"},
        )
    ).status_code == 200
    assert (
        await client.get("/api/v1/organizations/current/members", headers=agronomist)
    ).status_code == 403

    admin, _ = await _invite_and_accept(client, monkeypatch, owner, farm["id"], "admin")
    visible_to_admin = (await client.get("/api/v1/locations", headers=admin)).json()
    assert {item["id"] for item in visible_to_admin} == {farm["id"]}
    assert (
        await client.get(f"/api/v1/locations/{sibling_farm['id']}", headers=admin)
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/organizations/current/invitations",
            headers=admin,
            json={"email": f"wide-{uuid.uuid4().hex}@example.com", "role": "viewer"},
        )
    ).status_code == 409
    assert (
        await client.get("/api/v1/organizations/current/members", headers=admin)
    ).status_code == 200

    revoked_token = f"token-{uuid.uuid4().hex}"
    monkeypatch.setattr(service, "generate_invitation_token", lambda: revoked_token)
    revoked_invitation = await client.post(
        "/api/v1/organizations/current/invitations",
        headers=owner,
        json={"email": f"revoked-{uuid.uuid4().hex}@example.com", "role": "viewer"},
    )
    assert revoked_invitation.status_code == 201
    invitations = await client.get("/api/v1/organizations/current/invitations", headers=owner)
    assert revoked_invitation.json()["id"] in {item["id"] for item in invitations.json()}
    assert (
        await client.delete(
            f"/api/v1/organizations/current/invitations/{revoked_invitation.json()['id']}",
            headers=owner,
        )
    ).status_code == 204
    assert (
        await client.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": revoked_token, "password": PASSWORD},
        )
    ).status_code == 410

    other_owner = await _owner(client)
    other_farm = (await client.post("/api/v1/locations", headers=other_owner, json=FARM)).json()
    assert (
        await client.get(f"/api/v1/locations/{other_farm['id']}", headers=viewer)
    ).status_code == 404

    assert (
        await client.delete(f"/api/v1/organizations/current/members/{viewer_id}", headers=owner)
    ).status_code == 204
    assert (await client.get("/api/v1/locations", headers=viewer)).status_code == 401
    audit = await client.get("/api/v1/organizations/current/access-audit", headers=owner)
    assert {item["action"] for item in audit.json()} >= {
        "invitation.created",
        "invitation.accepted",
        "member.revoked",
    }
