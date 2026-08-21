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


def get_numeric_rain_forecast_provider(settings: Settings) -> WeatherProvider:
    """Open-Meteo, directly — bypassing INMET/CPTEC entirely.

    The normal fallback chain (``get_weather_provider``) only advances to
    the next tier when the current one *raises* — CPTEC's ``get_forecast``
    always succeeds, it just never populates ``precipitation_mm`` (it only
    gives condition codes/text, see ADR-0011/0014). So whenever CPTEC is
    the one answering (INMET down, which it was for most of this project's
    development), any feature needing real numeric rain — the spray window
    and soil trafficability signal — would otherwise get every day back
    with ``precipitation_mm=None`` and have to call it "unknown", even
    though a source that *does* have the number (Open-Meteo) is right
    there. Open-Meteo is the only one of the three that ever gives numeric
    precipitation at all (ADR-0015) — asking it directly, instead of
    hoping the chain happens to reach it, is what actually fixes that
    (FASE 24, ADR-0020).

    Still respects ``weather_provider=mock`` — tests/local dev in mock mode
    must never make a real network call just because this bypasses the
    normal chain.
    """
    if settings.weather_provider.lower() == "mock":
        return MockWeatherProvider()
    return _build_open_meteo(settings)


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
