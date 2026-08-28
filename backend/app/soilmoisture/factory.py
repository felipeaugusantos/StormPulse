"""Soil-moisture provider selection (item NASA).

Mock when `soil_moisture_enabled=false`; NASA POWER otherwise. No
credentials needed — unlike NDVI/Sentinel Hub, this is a fully open,
unauthenticated government API, so the flag exists only to let an operator
turn a new external call off if it ever misbehaves in production, not to
gate on missing credentials.
"""

from __future__ import annotations

from app.core.config import Settings
from app.soilmoisture.mock import MockSoilMoistureProvider
from app.soilmoisture.nasa_power import NasaPowerSoilMoistureProvider
from app.soilmoisture.provider import SoilMoistureProvider


def get_soil_moisture_provider(settings: Settings) -> SoilMoistureProvider:
    if not settings.soil_moisture_enabled:
        return MockSoilMoistureProvider()
    return NasaPowerSoilMoistureProvider(
        base_url=settings.soil_moisture_nasa_power_url,
        http_timeout_seconds=settings.soil_moisture_http_timeout_seconds,
    )
