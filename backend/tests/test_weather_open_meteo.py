"""Tests for OpenMeteoWeatherProvider — the third redundancy tier (FASE 20).

Network calls are faked with ``httpx.MockTransport`` — the fixture JSON
mirrors the real response verified live for Ribeirão Preto on 2026-08-20
via both ``api.open-meteo.com/v1/forecast`` and
``archive-api.open-meteo.com/v1/archive``.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.core.enums import WeatherSourceKind
from app.weather.open_meteo import OpenMeteoWeatherProvider, WeatherProviderUnavailableError

_FORECAST_PAYLOAD = {
    "latitude": -21.19508,
    "longitude": -47.79248,
    "current": {
        "time": "2026-08-20T17:15",
        "temperature_2m": 33.1,
        "wind_speed_10m": 11.3,
        "wind_gusts_10m": 31.7,
        "precipitation": 0.0,
    },
    "daily": {
        "time": ["2026-08-20", "2026-08-21"],
        "temperature_2m_max": [33.1, 27.9],
        "temperature_2m_min": [17.4, 19.4],
        "temperature_2m_mean": [25.3, 23.1],
        "precipitation_sum": [0.0, 4.2],
        "precipitation_probability_max": [0, 47],
        "relative_humidity_2m_mean": [58.0, 71.0],
        "relative_humidity_2m_max": [88.0, 95.0],
        "wind_gusts_10m_max": [31.7, 42.5],
        "et0_fao_evapotranspiration": [5.1, 3.4],
        "cape_max": [1250.0, 2980.0],
    },
}

_ARCHIVE_PAYLOAD = {
    "latitude": -21.19508,
    "longitude": -47.79248,
    "daily": {
        "time": ["2026-08-18", "2026-08-19"],
        "precipitation_sum": [0.0, 0.1],
    },
}


def _make_provider(transport: httpx.MockTransport) -> OpenMeteoWeatherProvider:
    return OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        client=httpx.AsyncClient(transport=transport),
    )


async def test_get_current_data_maps_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    current = await provider.get_current_data(-21.1775, -47.8103)

    assert current.provenance.source_name == "Open-Meteo"
    assert current.provenance.source_kind == WeatherSourceKind.FORECAST_MODEL
    assert current.provenance.is_mock is False
    assert current.temperature_c == 33.1
    assert current.wind_kmh == 11.3
    assert current.wind_gusts_kmh == 31.7


async def test_get_forecast_includes_real_numeric_precipitation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    forecast = await provider.get_forecast(-21.1775, -47.8103)

    assert len(forecast.points) == 2
    assert forecast.points[0].temperature_c == 33.1
    assert forecast.points[0].temperature_min_c == 17.4
    # Unlike INMET/CPTEC, these are real numbers, not left unset.
    assert forecast.points[1].precipitation_probability == 47
    assert forecast.points[1].precipitation_mm == 4.2


async def test_get_forecast_includes_cape_and_water_balance_fields() -> None:
    """FASE 25 (ADR-0021): storm-instability (CAPE) and water-balance/
    disease-risk (ET0, humidity) daily aggregates."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    forecast = await provider.get_forecast(-21.1775, -47.8103)

    first, second = forecast.points
    assert first.temperature_mean_c == 25.3
    assert first.humidity_mean_percent == 58.0
    assert first.humidity_max_percent == 88.0
    assert first.wind_gusts_max_kmh == 31.7
    assert first.evapotranspiration_mm == 5.1
    assert first.cape_max_jkg == 1250.0
    assert second.cape_max_jkg == 2980.0


async def test_get_recent_rainfall_parses_archive_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "archive-api" in str(request.url)
        return httpx.Response(200, json=_ARCHIVE_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    rainfall = await provider.get_recent_rainfall(-21.1775, -47.8103, days=2)

    assert len(rainfall.daily) == 2
    assert rainfall.daily[0].date == date(2026, 8, 18)
    assert rainfall.daily[1].total_mm == 0.1


async def test_radar_and_warnings_are_honestly_unavailable() -> None:
    provider = _make_provider(httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_radar_frames()
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_warnings(-21.1775, -47.8103)


async def test_get_current_data_raises_on_missing_current_block() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"daily": {}})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_current_data(-21.1775, -47.8103)


async def test_get_forecast_raises_on_missing_daily_block() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"current": {}})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_forecast(-21.1775, -47.8103)


async def test_get_forecast_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_forecast(-21.1775, -47.8103)


async def test_aclose_closes_the_underlying_client() -> None:
    provider = _make_provider(httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    await provider.aclose()
