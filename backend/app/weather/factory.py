"""Weather provider selection.

Chooses the active provider from settings. 'mock' (simulated), 'inmet'
(real, FASE 13) and 'cptec' (real, FASE 17) are registered here without
touching the storm engine. When 'inmet' is selected and
``cptec_fallback_enabled`` is true (the default — see ADR-0011), the INMET
provider is wrapped so that current-conditions/forecast calls automatically
fall back to CPTEC when INMET fails.
"""

from __future__ import annotations

from app.core.config import Settings
from app.weather.cptec import CptecWeatherProvider
from app.weather.fallback import FallbackWeatherProvider
from app.weather.inmet import InmetWeatherProvider
from app.weather.mock import MockWeatherProvider
from app.weather.provider import WeatherProvider


def _build_cptec(settings: Settings) -> CptecWeatherProvider:
    return CptecWeatherProvider(
        base_url=settings.cptec_base_url,
        http_timeout_seconds=settings.cptec_http_timeout_seconds,
    )


def get_weather_provider(settings: Settings) -> WeatherProvider:
    provider = settings.weather_provider.lower()
    if provider == "mock":
        return MockWeatherProvider()
    if provider == "inmet":
        inmet = InmetWeatherProvider(
            base_url=settings.inmet_base_url,
            avisos_url=settings.inmet_avisos_url,
            previsao_url=settings.inmet_previsao_url,
            ibge_localidades_url=settings.ibge_localidades_url,
            http_timeout_seconds=settings.inmet_http_timeout_seconds,
            min_rain_rate_mm_h=settings.inmet_min_rain_rate_mm_h,
            max_station_distance_km=settings.inmet_max_station_distance_km,
        )
        if settings.cptec_fallback_enabled:
            return FallbackWeatherProvider(inmet, _build_cptec(settings))
        return inmet
    if provider == "cptec":
        return _build_cptec(settings)
    raise ValueError(
        f"Unknown weather provider {settings.weather_provider!r}. "
        "Available providers: 'mock', 'inmet', 'cptec'."
    )
