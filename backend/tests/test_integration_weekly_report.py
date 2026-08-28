"""Integration tests for the talhão weekly-report endpoint (FASE 32).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Rainfall comes from a live weather-provider call (same as
``/agro/rainfall`` elsewhere in this suite) — alerts/NDVI are inserted
directly via the sync workers session, same pattern as
``test_integration_ndvi.py``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.alerts.models import Alert
from app.core.config import Settings
from app.core.enums import AlertEventType, RiskLevel, WeatherSourceKind
from app.main import create_app
from app.ndvi.models import NdviReading
from app.soilmoisture.provider import (
    SoilMoistureObservation,
    SoilMoistureProvider,
    SoilMoistureProviderUnavailableError,
)
from app.weather.provider import Provenance
from tests.conftest import register_and_login
from workers.db import session_scope

pytestmark = pytest.mark.integration

_BOUNDARY = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [[[-47.81, -21.18], [-47.80, -21.18], [-47.80, -21.17], [-47.81, -21.18]]],
    }
)


async def _auth_headers(client: AsyncClient) -> dict[str, str]:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def _create_farm_and_talhao(client: AsyncClient, headers: dict[str, str]) -> tuple[str, str]:
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
    talhao = (
        await client.post(
            "/api/v1/locations",
            json={
                "name": "Talhão",
                "latitude": -21.18,
                "longitude": -47.81,
                "parent_location_id": farm["id"],
                "crop": "soja",
                "boundary_geojson": _BOUNDARY,
            },
            headers=headers,
        )
    ).json()
    return farm["id"], talhao["id"]


async def test_weekly_report_404s_for_a_farm(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 404


async def test_weekly_report_includes_period_and_data_within_it(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    within_period = datetime.now(UTC) - timedelta(days=3)
    outside_period = datetime.now(UTC) - timedelta(days=20)
    with session_scope() as session:
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=talhao_id,
                event_type=AlertEventType.DRY_SPELL_WARNING,
                level=RiskLevel.ORANGE,
                title="Sequência sem chuva",
                message="7 dias consecutivos sem chuva mensurável.",
                dedup_key=f"{talhao_id}:{uuid.uuid4().hex}:dry_spell_warning",
                created_at=within_period,
            )
        )
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=talhao_id,
                event_type=AlertEventType.DRY_SPELL_WARNING,
                level=RiskLevel.ORANGE,
                title="Sequência sem chuva (antiga)",
                message="Fora do período do relatório.",
                dedup_key=f"{talhao_id}:{uuid.uuid4().hex}:dry_spell_warning",
                created_at=outside_period,
            )
        )
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=within_period,
                ndvi_mean=0.55,
                valid_pixel_percent=88.0,
                is_mock=True,
            )
        )
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=outside_period,
                ndvi_mean=0.10,
                valid_pixel_percent=70.0,
                is_mock=True,
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["location_name"] == "Talhão"
    assert body["crop"] == "soja"
    assert body["rainfall_total_mm"] >= 0
    assert 0 <= body["dry_days_count"] <= 7
    # Derived from the drawn boundary — never a guessed/manual value.
    assert body["area_ha"] is not None
    assert body["area_ha"] > 0
    # No ANTHROPIC_API_KEY in the test settings fixture — must degrade to
    # None, never a fabricated summary and never a failed request.
    assert body["ai_summary"] is None

    alert_titles = [a["title"] for a in body["alerts"]]
    assert "Sequência sem chuva" in alert_titles
    assert "Sequência sem chuva (antiga)" not in alert_titles

    ndvi_values = [n["ndvi_mean"] for n in body["ndvi_readings"]]
    assert 0.55 in ndvi_values
    assert 0.10 not in ndvi_values


async def test_weekly_report_soil_moisture_is_null_when_the_source_is_disabled(
    client: AsyncClient,
) -> None:
    """SOIL_MOISTURE_ENABLED=false is the default in the test settings
    fixture — the report must omit the section entirely (`None`), never
    silently show a mock reading just because a source is off."""
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["soil_moisture"] is None


class _FakeSoilMoistureProvider(SoilMoistureProvider):
    """Standing in for NasaPowerSoilMoistureProvider — the real one is unit-
    tested against a mocked transport in test_soilmoisture_nasa_power.py;
    this exercises app.locations.service's own wiring (the enabled gate,
    and graceful degradation on failure) without a real network call."""

    def __init__(self, *, raise_error: bool = False) -> None:
        self._raise_error = raise_error

    @property
    def name(self) -> str:
        return "FAKE"

    async def get_soil_moisture(self, latitude: float, longitude: float) -> SoilMoistureObservation:
        if self._raise_error:
            raise SoilMoistureProviderUnavailableError("indisponível (fake)")
        return SoilMoistureObservation(
            provenance=Provenance(
                source_name="FAKE", source_kind=WeatherSourceKind.FORECAST_MODEL, is_mock=False
            ),
            observed_at=datetime.now(UTC).date(),
            surface_wetness_percent=33.0,
            root_zone_wetness_percent=46.0,
            profile_wetness_percent=46.0,
        )


@pytest.fixture
async def soil_moisture_client() -> AsyncIterator[AsyncClient]:
    """Same shape as conftest's own ``client`` fixture, but with
    ``soil_moisture_enabled=True`` — a dedicated app instance instead of
    overriding the shared fixture, so the "disabled by default" tests
    above stay on the real default."""
    settings = Settings(
        environment="test",
        log_json=False,
        log_level="WARNING",
        auth_rate_limit_max=10_000,
        default_rate_limit_max=10_000,
        public_rate_limit_max=10_000,
        soil_moisture_enabled=True,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as ac,
    ):
        yield ac


async def test_weekly_report_includes_soil_moisture_when_enabled(
    soil_moisture_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.locations.service.get_soil_moisture_provider",
        lambda settings: _FakeSoilMoistureProvider(),
    )
    headers = await _auth_headers(soil_moisture_client)
    _, talhao_id = await _create_farm_and_talhao(soil_moisture_client, headers)

    resp = await soil_moisture_client.get(
        f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()["soil_moisture"]
    assert body is not None
    assert body["surface_wetness_percent"] == 33.0
    assert body["root_zone_wetness_percent"] == 46.0
    assert body["is_mock"] is False


async def test_weekly_report_soil_moisture_degrades_to_none_on_provider_failure(
    soil_moisture_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.locations.service.get_soil_moisture_provider",
        lambda settings: _FakeSoilMoistureProvider(raise_error=True),
    )
    headers = await _auth_headers(soil_moisture_client)
    _, talhao_id = await _create_farm_and_talhao(soil_moisture_client, headers)

    resp = await soil_moisture_client.get(
        f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers
    )
    # Never a 500 — a soil-moisture failure must never fail the whole
    # report, same rule as the rainfall provider's own try/except above.
    assert resp.status_code == 200
    assert resp.json()["soil_moisture"] is None


async def test_weekly_report_another_users_talhao_is_404(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{talhao_id}/agro/weekly-report", headers=headers_b)
    assert resp.status_code == 404
