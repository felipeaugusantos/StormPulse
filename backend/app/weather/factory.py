"""Weather provider selection.

Chooses the active provider from settings. 'mock' (simulated) and 'inmet'
(real, FASE 13) are registered here without touching the storm engine.
"""

from __future__ import annotations

from app.core.config import Settings
from app.weather.inmet import InmetWeatherProvider
from app.weather.mock import MockWeatherProvider
from app.weather.provider import WeatherProvider


def get_weather_provider(settings: Settings) -> WeatherProvider:
    provider = settings.weather_provider.lower()
    if provider == "mock":
        return MockWeatherProvider()
    if provider == "inmet":
        return InmetWeatherProvider(
            base_url=settings.inmet_base_url,
            avisos_url=settings.inmet_avisos_url,
            previsao_url=settings.inmet_previsao_url,
            ibge_localidades_url=settings.ibge_localidades_url,
            http_timeout_seconds=settings.inmet_http_timeout_seconds,
            min_rain_rate_mm_h=settings.inmet_min_rain_rate_mm_h,
            max_station_distance_km=settings.inmet_max_station_distance_km,
        )
    raise ValueError(
        f"Unknown weather provider {settings.weather_provider!r}. "
        "Available providers: 'mock', 'inmet'."
    )
