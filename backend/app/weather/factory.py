"""Weather provider selection.

Chooses the active provider from settings. Only the MOCK provider exists now;
real sources register here in FASE 13 without touching the storm engine.
"""

from __future__ import annotations

from app.core.config import Settings
from app.weather.mock import MockWeatherProvider
from app.weather.provider import WeatherProvider


def get_weather_provider(settings: Settings) -> WeatherProvider:
    provider = settings.weather_provider.lower()
    if provider == "mock":
        return MockWeatherProvider()
    raise ValueError(
        f"Unknown weather provider {settings.weather_provider!r}. "
        "Only 'mock' is available until FASE 13."
    )
