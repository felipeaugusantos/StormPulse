"""Integration tests for the Caderno de Campo endpoints (Fase 6, ADR-0090).

Needs real Postgres+Redis and MinIO — auto-skipped without Postgres/Redis
(see ``conftest.py``); photo-upload tests need a real MinIO reachable at
``FIELDNOTES_STORAGE_ENDPOINT`` (CI starts one — see ``.github/workflows/
ci.yml``).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import register_and_login

pytestmark = pytest.mark.integration

_LOCATION_PAYLOAD = {
    "name": "Fazenda (teste caderno de campo)",
    "kind": "farm",
    "latitude": -21.1775,
    "longitude": -47.8103,
    "radius_km": 10,
}


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_location(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post("/api/v1/locations", json=_LOCATION_PAYLOAD, headers=headers)
    assert resp.status_code == 201
    return str(resp.json()["id"])


# ---------------------------------------------------------------------------
# Occurrences
# ---------------------------------------------------------------------------


async def test_create_and_list_occurrence(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    resp = await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences",
        json={
            "category": "praga",
            "description": "Lagarta encontrada na folha.",
            "latitude": -21.1775,
            "longitude": -47.8103,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"
    assert body["version"] == 1

    list_resp = await client.get(
        f"/api/v1/locations/{location_id}/field-occurrences", headers=headers
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


async def test_create_occurrence_with_client_supplied_id_is_idempotent_on_retry(
    client: AsyncClient,
) -> None:
    """Fase 6 (ADR-0090): the mobile app generates the id offline and may
    replay the same create after a timeout — a second POST with the same
    id must return the existing row, never a duplicate-key error."""
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    client_id = str(uuid.uuid4())

    payload = {
        "id": client_id,
        "category": "seca",
        "description": "Solo rachado.",
        "latitude": -21.1775,
        "longitude": -47.8103,
    }
    first = await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences", json=payload, headers=headers
    )
    second = await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences", json=payload, headers=headers
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"] == client_id

    list_resp = await client.get(
        f"/api/v1/locations/{location_id}/field-occurrences", headers=headers
    )
    assert len(list_resp.json()) == 1


async def test_update_occurrence_with_stale_version_is_a_conflict(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    create_resp = await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences",
        json={
            "category": "praga",
            "description": "Descrição original.",
            "latitude": -21.1775,
            "longitude": -47.8103,
        },
        headers=headers,
    )
    occurrence_id = create_resp.json()["id"]

    first_update = await client.patch(
        f"/api/v1/field-occurrences/{occurrence_id}",
        json={"base_version": 1, "status": "resolved"},
        headers=headers,
    )
    assert first_update.status_code == 200
    assert first_update.json()["version"] == 2

    stale_update = await client.patch(
        f"/api/v1/field-occurrences/{occurrence_id}",
        json={"base_version": 1, "description": "Tentando sobrescrever com dado antigo."},
        headers=headers,
    )
    assert stale_update.status_code == 409
    # Never silently overwritten — the description from the first update
    # (unchanged since) must still be there.
    get_resp = await client.get(
        f"/api/v1/locations/{location_id}/field-occurrences", headers=headers
    )
    assert get_resp.json()[0]["description"] == "Descrição original."


async def test_another_tenants_occurrence_update_is_404(client: AsyncClient) -> None:
    owner_headers = await _auth_headers(client)
    location_id = await _create_location(client, owner_headers)
    create_resp = await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences",
        json={
            "category": "praga",
            "description": "x",
            "latitude": -21.1775,
            "longitude": -47.8103,
        },
        headers=owner_headers,
    )
    occurrence_id = create_resp.json()["id"]

    other_headers = await _auth_headers(client)
    resp = await client.patch(
        f"/api/v1/field-occurrences/{occurrence_id}",
        json={"base_version": 1, "status": "resolved"},
        headers=other_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Inspections + photos
# ---------------------------------------------------------------------------


async def test_create_inspection_linked_to_an_occurrence(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    occurrence_id = (
        await client.post(
            f"/api/v1/locations/{location_id}/field-occurrences",
            json={
                "category": "praga",
                "description": "x",
                "latitude": -21.1775,
                "longitude": -47.8103,
            },
            headers=headers,
        )
    ).json()["id"]

    resp = await client.post(
        f"/api/v1/locations/{location_id}/field-inspections",
        json={"occurrence_id": occurrence_id, "notes": "Confirmada infestação leve."},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["occurrence_id"] == occurrence_id
    assert resp.json()["version"] == 1


async def test_upload_and_list_inspection_photo(client: AsyncClient) -> None:
    """Needs a real MinIO reachable — see module docstring."""
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    inspection_id = (
        await client.post(
            f"/api/v1/locations/{location_id}/field-inspections",
            json={"notes": "Inspeção de rotina."},
            headers=headers,
        )
    ).json()["id"]

    upload_resp = await client.post(
        f"/api/v1/field-inspections/{inspection_id}/photos",
        files={"file": ("folha.jpg", b"fake-jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    assert upload_resp.status_code == 201
    photo = upload_resp.json()
    assert photo["content_type"] == "image/jpeg"
    assert photo["size_bytes"] == len(b"fake-jpeg-bytes")
    assert photo["url"].startswith("http")

    list_resp = await client.get(
        f"/api/v1/field-inspections/{inspection_id}/photos", headers=headers
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    # Never a public/permanent URL — always freshly signed.
    assert "X-Amz-Signature" in list_resp.json()[0]["url"] or "?" in list_resp.json()[0]["url"]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


async def test_create_task_and_complete_it(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    create_resp = await client.post(
        f"/api/v1/locations/{location_id}/field-tasks",
        json={"title": "Aplicar defensivo", "assigned_to": me["id"]},
        headers=headers,
    )
    assert create_resp.status_code == 201
    task = create_resp.json()
    assert task["status"] == "pending"
    assert task["completed_at"] is None

    complete_resp = await client.patch(
        f"/api/v1/field-tasks/{task['id']}",
        json={"base_version": 1, "status": "done"},
        headers=headers,
    )
    assert complete_resp.status_code == 200
    completed = complete_resp.json()
    assert completed["status"] == "done"
    assert completed["completed_by"] == me["id"]
    assert completed["completed_at"] is not None


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


async def test_timeline_merges_occurrences_inspections_and_tasks(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    location_id = await _create_location(client, headers)

    await client.post(
        f"/api/v1/locations/{location_id}/field-occurrences",
        json={
            "category": "praga",
            "description": "Ocorrência de teste.",
            "latitude": -21.1775,
            "longitude": -47.8103,
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/locations/{location_id}/field-inspections",
        json={"notes": "Inspeção de teste."},
        headers=headers,
    )
    await client.post(
        f"/api/v1/locations/{location_id}/field-tasks",
        json={"title": "Tarefa de teste."},
        headers=headers,
    )

    resp = await client.get(f"/api/v1/locations/{location_id}/field-timeline", headers=headers)
    assert resp.status_code == 200
    kinds = {entry["kind"] for entry in resp.json()}
    assert kinds == {"occurrence", "inspection", "task"}


async def test_nonexistent_location_404s_everywhere(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    fake_id = uuid.uuid4()

    assert (
        await client.get(f"/api/v1/locations/{fake_id}/field-occurrences", headers=headers)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/locations/{fake_id}/field-timeline", headers=headers)
    ).status_code == 404
