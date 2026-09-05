"""Integration test for the ingestion pipeline materializing storms + risk.

Needs real Postgres+PostGIS and Redis — auto-skipped otherwise (see
``conftest.py``). Mirrors the "Integration — worker pipeline materializes
storms + risk" step already exercised via ``docker compose run ...
workers.run_once`` + curl in ``.github/workflows/ci.yml``, calling
``run_ingestion_cycle`` directly instead of shelling out.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.alerts.models import Alert
from app.core.enums import NotificationStatus, WeatherSourceKind
from app.notifications.models import Notification
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
    WeatherProviderUnavailableError,
)
from tests.conftest import register_and_login
from workers.db import session_scope
from workers.pipeline_service import CycleSummary, run_ingestion_cycle

pytestmark = pytest.mark.integration

# Matches MockWeatherProvider's fixed mock cell footprint (see
# backend/app/weather/mock.py) so the location falls within its radius.
_LOCATION_NEAR_MOCK_STORM = {
    "name": "Casa",
    "kind": "home",
    "latitude": -23.5,
    "longitude": -46.6,
    "radius_km": 80,
}


async def test_pipeline_cycle_materializes_storms_and_risk(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = (
        await client.post("/api/v1/locations", json=_LOCATION_NEAR_MOCK_STORM, headers=headers)
    ).json()
    location_id = created["id"]

    def _run_one_cycle() -> CycleSummary:
        # run_ingestion_cycle is synchronous and calls asyncio.run() itself
        # (as Celery's sync worker does) — it can't run on the loop this
        # async test is already on, so it gets its own thread instead.
        with session_scope() as session:
            return run_ingestion_cycle(session)

    summary = await asyncio.to_thread(_run_one_cycle)
    assert summary.cells >= 1
    assert summary.risks >= 1

    storms_resp = await client.get("/api/v1/storms", headers=headers)
    assert storms_resp.status_code == 200
    assert len(storms_resp.json()) >= 1

    nearby_resp = await client.get(
        "/api/v1/storms/nearby",
        params={"lat": -23.5, "lon": -46.6, "radius_km": 80},
        headers=headers,
    )
    assert nearby_resp.status_code == 200
    assert len(nearby_resp.json()) >= 1

    risk_resp = await client.get(f"/api/v1/locations/{location_id}/risk", headers=headers)
    assert risk_resp.status_code == 200
    risk = risk_resp.json()
    assert risk["is_mock"] is True
    assert risk["experimental"] is True


async def test_disabled_severe_storm_preference_suppresses_the_alert(
    client: AsyncClient,
) -> None:
    """Item 'AlertPreference é um recurso morto' — the toggle used to
    persist and come back in the API response without ever being read by
    the pipeline that actually emits alerts."""
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        **_LOCATION_NEAR_MOCK_STORM,
        "alert_preferences": [{"alert_type": "severe_storm", "enabled": False}],
    }
    created = (await client.post("/api/v1/locations", json=payload, headers=headers)).json()
    location_id = created["id"]

    def _run_one_cycle() -> CycleSummary:
        with session_scope() as session:
            return run_ingestion_cycle(session)

    summary = await asyncio.to_thread(_run_one_cycle)
    assert summary.suppressed >= 1
    # A suppressed alert is a real, honest non-attempt — never counted as
    # a delivered/queued one.
    assert summary.alerts == 0

    def _load_notification_statuses() -> list[NotificationStatus]:
        with session_scope() as session:
            alert_ids = session.scalars(
                select(Alert.id).where(Alert.location_id == uuid.UUID(location_id))
            ).all()
            return list(
                session.scalars(
                    select(Notification.status).where(Notification.alert_id.in_(alert_ids))
                ).all()
            )

    statuses = await asyncio.to_thread(_load_notification_statuses)
    # The Alert itself is still recorded (real detected event, worth
    # keeping in history) — only delivery is suppressed.
    assert len(statuses) >= 1
    assert all(s == NotificationStatus.SUPPRESSED for s in statuses)


class _RadarUnavailableProvider(WeatherProvider):
    """Every fallback tier failing for ``get_radar_frames`` — the exact
    shape a sustained INMET outage produces once CPTEC/Open-Meteo's own
    (structural, not transient) lack of radar data is chained on top
    (confirmed live in production 2026-08-28: this crashed every single
    5-minute cycle, with zero StormCell rows ever persisted, until
    ``run_ingestion_cycle`` started catching it)."""

    @property
    def name(self) -> str:
        return "FAKE-NO-RADAR"

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.RADAR

    def _provenance(self) -> Provenance:
        return Provenance(source_name=self.name, source_kind=self.kind, is_mock=False)

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=datetime.now(UTC),
            latitude=latitude,
            longitude=longitude,
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        raise WeatherProviderUnavailableError("no radar data from any provider in the chain")

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        return []

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        return Forecast(provenance=self._provenance(), latitude=latitude, longitude=longitude)

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        return RainfallHistory(
            provenance=self._provenance(), latitude=latitude, longitude=longitude
        )


async def test_pipeline_cycle_survives_a_total_radar_outage(client: AsyncClient) -> None:
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post("/api/v1/locations", json=_LOCATION_NEAR_MOCK_STORM, headers=headers)

    def _run_one_cycle() -> CycleSummary:
        with session_scope() as session:
            return run_ingestion_cycle(session, provider=_RadarUnavailableProvider())

    summary = await asyncio.to_thread(_run_one_cycle)
    assert summary.frames == 0
    assert summary.cells == 0
    assert summary.risks == 0
    assert summary.alerts == 0
