"""Weather provider selection.

Chooses the active provider from settings. 'mock' (simulated), 'inmet'
(real, FASE 13), 'cptec' (real, FASE 17) and 'open_meteo' (real, FASE 20)
are registered here without touching the storm engine. When 'inmet' is
selected, it's wrapped in up to two automatic fallback tiers — CPTEC first
(``cptec_fallback_enabled``, default on — see ADR-0011), then Open-Meteo
(``open_meteo_fallback_enabled``, default on — see ADR-0015) — each tried
in order, per method, only when the one before it fails.
"""

from __future__ import annotations

from app.core.config import Settings
from app.weather.cptec import CptecWeatherProvider
from app.weather.fallback import FallbackWeatherProvider
from app.weather.inmet import InmetWeatherProvider
from app.weather.mock import MockWeatherProvider
from app.weather.open_meteo import OpenMeteoWeatherProvider
from app.weather.provider import WeatherProvider


def _build_cptec(settings: Settings) -> CptecWeatherProvider:
    return CptecWeatherProvider(
        base_url=settings.cptec_base_url,
        http_timeout_seconds=settings.cptec_http_timeout_seconds,
    )


def _build_open_meteo(settings: Settings) -> OpenMeteoWeatherProvider:
    return OpenMeteoWeatherProvider(
        forecast_url=settings.open_meteo_forecast_url,
        archive_url=settings.open_meteo_archive_url,
        http_timeout_seconds=settings.open_meteo_http_timeout_seconds,
    )


def _with_fallback_chain(primary: WeatherProvider, settings: Settings) -> WeatherProvider:
    provider = primary
    if settings.cptec_fallback_enabled:
        provider = FallbackWeatherProvider(provider, _build_cptec(settings))
    if settings.open_meteo_fallback_enabled:
        provider = FallbackWeatherProvider(provider, _build_open_meteo(settings))
    return provider


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
        return _with_fallback_chain(inmet, settings)
    if provider == "cptec":
        return _build_cptec(settings)
    if provider == "open_meteo":
        return _build_open_meteo(settings)
    raise ValueError(
        f"Unknown weather provider {settings.weather_provider!r}. "
        "Available providers: 'mock', 'inmet', 'cptec', 'open_meteo'."
    )
