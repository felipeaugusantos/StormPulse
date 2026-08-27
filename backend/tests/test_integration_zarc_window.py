"""Integration tests for the talhão ZARC planting-window endpoint (item
ZARC, ADR-0069).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
``ZarcRiskWindow`` rows are inserted directly via the sync workers session
(same pattern as ``test_integration_weekly_report.py`` for Alert/NDVI).
The INMET/IBGE geocode lookup is swapped for a fake coroutine — same
"swap a collaborator, not the DB" approach as
``test_official_warnings_pipeline.py``'s ``_FakeProvider`` — so this never
makes a live network call.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.locations import zarc_service
from app.zarc.models import ZarcRiskWindow
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration


def _unique_geocode() -> str:
    # ZarcRiskWindow is global reference data (no per-test tenant
    # isolation, no cleanup) — a unique geocode per test keeps rows one
    # test inserts from ever being visible to another's query, instead
    # of relying on cross-test cleanup of a shared value.
    return uuid.uuid4().hex[:10]


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_farm_and_talhao(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    crop: str | None = "soja",
    soil_type: str | None = "textura_media",
) -> tuple[str, str]:
    farm = (
        await client.post(
            "/api/v1/locations",
            json={
                "name": "Fazenda",
                "kind": "farm",
                "latitude": -21.18,
                "longitude": -47.81,
                "radius_km": 10,
            },
            headers=headers,
        )
    ).json()
    payload: dict[str, object] = {
        "name": "Talhão",
        "latitude": -21.18,
        "longitude": -47.81,
        "parent_location_id": farm["id"],
    }
    if crop is not None:
        payload["crop"] = crop
    if soil_type is not None:
        payload["soil_type"] = soil_type
    talhao = (await client.post("/api/v1/locations", json=payload, headers=headers)).json()
    return farm["id"], talhao["id"]


def _fake_resolver(monkeypatch: pytest.MonkeyPatch, geocode: str) -> None:
    async def _fake(*args: object, **kwargs: object) -> str:
        return geocode

    monkeypatch.setattr(zarc_service, "resolve_municipio_geocode", _fake)


async def test_zarc_window_404s_for_a_farm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_resolver(monkeypatch, _unique_geocode())
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/zarc-window", headers=headers)
    assert resp.status_code == 404


async def test_zarc_window_404s_when_talhao_has_no_crop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_resolver(monkeypatch, _unique_geocode())
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers, crop=None)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/zarc-window", headers=headers)
    assert resp.status_code == 404


async def test_zarc_window_404s_when_no_row_matches_the_crop(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    geocode = _unique_geocode()
    _fake_resolver(monkeypatch, geocode)
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers, crop="milho")
    with session_scope() as session:
        session.add(
            ZarcRiskWindow(
                geocodigo=geocode,
                uf="SP",
                municipio="Ribeirão Preto",
                cultura="Soja",
                cod_ciclo=20,
                cod_solo=2,
                safra_ini=2026,
                safra_fin=2027,
                portaria="Portaria 1/2026",
                decendios=[30 if i == 0 else 0 for i in range(36)],
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/zarc-window", headers=headers)
    assert resp.status_code == 404


async def test_zarc_window_returns_matching_rows(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    geocode = _unique_geocode()
    _fake_resolver(monkeypatch, geocode)
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(
        client, headers, crop="soja", soil_type="textura_media"
    )
    with session_scope() as session:
        session.add(
            ZarcRiskWindow(
                geocodigo=geocode,
                uf="SP",
                municipio="Ribeirão Preto",
                cultura="Soja",
                cod_ciclo=20,
                cod_solo=2,
                safra_ini=2026,
                safra_fin=2027,
                portaria="Portaria 1/2026",
                decendios=[30 if i == 0 else 0 for i in range(36)],
            )
        )
        # Different soil (arenoso=1) — must not be returned for a
        # textura_media (2) talhão.
        session.add(
            ZarcRiskWindow(
                geocodigo=geocode,
                uf="SP",
                municipio="Ribeirão Preto",
                cultura="Soja",
                cod_ciclo=20,
                cod_solo=1,
                safra_ini=2026,
                safra_fin=2027,
                portaria="Portaria 1/2026",
                decendios=[30 if i == 0 else 0 for i in range(36)],
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/zarc-window", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["geocodigo"] == geocode
    assert body["municipio"] == "Ribeirão Preto"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["cultura"] == "Soja"
    assert body["matches"][0]["ciclo_label"] == "Grupo I"
    assert len(body["matches"][0]["decendios"]) == 36
