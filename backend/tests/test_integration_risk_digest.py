"""Integration tests for the risk-digest endpoint (Fase 3-A, ADR-0087).

Needs real Postgres+Redis — auto-skipped otherwise (see ``conftest.py``).
Signals are inserted directly via the sync workers session, same pattern
as ``test_integration_weekly_report.py``.
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
from app.deforestation.models import DeforestationCheck
from app.main import create_app
from app.ndvi.models import NdviReading
from app.soilmoisture.provider import (
    SoilMoistureObservation,
    SoilMoistureProvider,
    SoilMoistureProviderUnavailableError,
)
from app.storms.models import StormRisk
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


async def test_risk_digest_is_all_none_for_a_brand_new_location(client: AsyncClient) -> None:
    """No pipeline cycle has run yet — every field is honestly `None`,
    never a 404 (unlike `/risk`, this endpoint always answers)."""
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/risk-digest", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["location_id"] == farm_id
    assert body["storm"] is None
    assert body["ndvi"] is None
    assert body["deforestation"] is None
    assert body["frost_last_alert"] is None
    assert body["dry_spell_last_alert"] is None
    assert body["soil_moisture"] is None


async def test_risk_digest_includes_the_latest_storm_risk(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    older = datetime.now(UTC) - timedelta(hours=2)
    newer = datetime.now(UTC) - timedelta(minutes=5)
    with session_scope() as session:
        session.add(
            StormRisk(
                tenant_id=me["tenant_id"],
                location_id=farm_id,
                severity=RiskLevel.YELLOW,
                rain_risk=0.2,
                computed_at=older,
                is_mock=True,
                experimental=True,
                detail={},
            )
        )
        session.add(
            StormRisk(
                tenant_id=me["tenant_id"],
                location_id=farm_id,
                severity=RiskLevel.ORANGE,
                rain_risk=0.6,
                storm_distance_km=12.0,
                eta_minutes=30,
                computed_at=newer,
                is_mock=True,
                experimental=True,
                detail={},
            )
        )

    resp = await client.get(f"/api/v1/locations/{farm_id}/risk-digest", headers=headers)
    assert resp.status_code == 200
    storm = resp.json()["storm"]
    assert storm is not None
    assert storm["severity"] == "orange"
    assert storm["eta_minutes"] == 30


async def test_risk_digest_includes_ndvi_only_for_the_talhao(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    farm_id, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            NdviReading(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                observed_at=datetime.now(UTC),
                ndvi_mean=0.62,
                valid_pixel_percent=91.0,
                is_mock=True,
            )
        )

    talhao_resp = await client.get(f"/api/v1/locations/{talhao_id}/risk-digest", headers=headers)
    assert talhao_resp.status_code == 200
    assert talhao_resp.json()["ndvi"]["ndvi_mean"] == 0.62

    farm_resp = await client.get(f"/api/v1/locations/{farm_id}/risk-digest", headers=headers)
    assert farm_resp.status_code == 200
    assert farm_resp.json()["ndvi"] is None


async def test_risk_digest_frost_and_dry_spell_are_last_alert_not_current_state(
    client: AsyncClient,
) -> None:
    """Fase 3-A ADR: frost/dry-spell have no "safe now" baseline — the
    digest can only ever report the last time an Alert fired, clearly
    historical, never a computed risk level."""
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            Alert(
                tenant_id=me["tenant_id"],
                user_id=me["id"],
                location_id=talhao_id,
                event_type=AlertEventType.FROST_WARNING,
                level=RiskLevel.RED,
                title="Geada severa prevista",
                message="Temperatura mínima abaixo de 0°C nas próximas 48h.",
                dedup_key=f"{talhao_id}:{uuid.uuid4().hex}:frost_warning",
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/risk-digest", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["frost_last_alert"] is not None
    assert body["frost_last_alert"]["title"] == "Geada severa prevista"
    assert body["frost_last_alert"]["level"] == "red"
    # No dry-spell alert was ever recorded for this talhão.
    assert body["dry_spell_last_alert"] is None


async def test_risk_digest_includes_deforestation_summary(client: AsyncClient) -> None:
    headers = await _auth_headers(client)
    _, talhao_id = await _create_farm_and_talhao(client, headers)
    me = (await client.get("/api/v1/users/me", headers=headers)).json()

    with session_scope() as session:
        session.add(
            DeforestationCheck(
                tenant_id=me["tenant_id"],
                location_id=talhao_id,
                source="DETER-AMZ",
                checked_at=datetime.now(UTC),
                alert_count=0,
                alerts_json="[]",
            )
        )

    resp = await client.get(f"/api/v1/locations/{talhao_id}/risk-digest", headers=headers)
    assert resp.status_code == 200
    deforestation = resp.json()["deforestation"]
    assert deforestation is not None
    assert deforestation["checked_sources"] == ["DETER-AMZ"]


async def test_risk_digest_soil_moisture_is_null_when_the_source_is_disabled(
    client: AsyncClient,
) -> None:
    headers = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers)

    resp = await client.get(f"/api/v1/locations/{farm_id}/risk-digest", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["soil_moisture"] is None


class _FakeSoilMoistureProvider(SoilMoistureProvider):
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


async def test_risk_digest_includes_soil_moisture_when_enabled(
    soil_moisture_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.locations.service.get_soil_moisture_provider",
        lambda settings: _FakeSoilMoistureProvider(),
    )
    headers = await _auth_headers(soil_moisture_client)
    farm_id, _ = await _create_farm_and_talhao(soil_moisture_client, headers)

    resp = await soil_moisture_client.get(
        f"/api/v1/locations/{farm_id}/risk-digest", headers=headers
    )
    assert resp.status_code == 200
    soil_moisture = resp.json()["soil_moisture"]
    assert soil_moisture is not None
    assert soil_moisture["surface_wetness_percent"] == 33.0


async def test_risk_digest_soil_moisture_degrades_to_none_on_provider_failure(
    soil_moisture_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.locations.service.get_soil_moisture_provider",
        lambda settings: _FakeSoilMoistureProvider(raise_error=True),
    )
    headers = await _auth_headers(soil_moisture_client)
    farm_id, _ = await _create_farm_and_talhao(soil_moisture_client, headers)

    resp = await soil_moisture_client.get(
        f"/api/v1/locations/{farm_id}/risk-digest", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["soil_moisture"] is None


async def test_risk_digest_never_404s_and_is_tenant_scoped(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client)
    farm_id, _ = await _create_farm_and_talhao(client, headers_a)

    headers_b = await _auth_headers(client)
    resp = await client.get(f"/api/v1/locations/{farm_id}/risk-digest", headers=headers_b)
    assert resp.status_code == 404
