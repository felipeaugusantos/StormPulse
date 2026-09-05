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
from app.weather.open_meteo import (
    ModelDailyPoint,
    ObservedDailyPoint,
    OpenMeteoWeatherProvider,
    WeatherProviderUnavailableError,
)

# Real response verified live (2026-09-05) for
# models=ecmwf_ifs025,gfs_seamless,icon_seamless — a single flat `daily`
# dict, each requested variable suffixed per model, one shared `time` array.
_MULTI_MODEL_PAYLOAD = {
    "latitude": -21.25,
    "longitude": -47.75,
    "daily": {
        "time": ["2026-09-05", "2026-09-06", "2026-09-07"],
        "temperature_2m_max_ecmwf_ifs025": [31.1, 23.9, 20.5],
        "precipitation_sum_ecmwf_ifs025": [2.40, 17.20, 15.50],
        "precipitation_probability_max_ecmwf_ifs025": [20, 80, 70],
        "wind_gusts_10m_max_ecmwf_ifs025": [25.0, 30.0, 28.0],
        "temperature_2m_max_gfs_seamless": [35.4, 23.6, 20.6],
        "precipitation_sum_gfs_seamless": [1.70, 9.30, 0.00],
        "precipitation_probability_max_gfs_seamless": [10, 40, 0],
        "wind_gusts_10m_max_gfs_seamless": [22.0, 27.0, 15.0],
    },
}

_FORECAST_PAYLOAD = {
    "latitude": -21.19508,
    "longitude": -47.79248,
    "current": {
        "time": "2026-08-20T17:15",
        "temperature_2m": 33.1,
        "wind_speed_10m": 11.3,
        "wind_gusts_10m": 31.7,
        "wind_direction_10m": 145.0,
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
    assert current.wind_direction_deg == 145.0


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


async def test_with_an_api_key_forecast_calls_use_the_customer_host_and_key() -> None:
    """Item ADR-0074: forecast/current calls route to the dedicated
    customer host with the key attached once a commercial subscription is
    configured — never the shared public host, which is where the real
    production throttling happened."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["apikey"] = request.url.params.get("apikey")
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        api_key="test-key-123",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.get_current_data(-21.1775, -47.8103)

    assert str(captured["url"]).startswith("https://customer-api.open-meteo.com/v1/forecast")
    assert captured["apikey"] == "test-key-123"


async def test_without_an_api_key_forecast_calls_use_the_public_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("apikey") is None
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    await provider.get_current_data(-21.1775, -47.8103)


async def test_an_api_key_never_reaches_the_archive_host() -> None:
    """The Standard plan doesn't include the historical/archive API (see
    the module docstring) — attaching the key there would likely 403, so
    `get_recent_rainfall` must keep hitting the free public archive host
    exactly as without a subscription, key or no key."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "archive-api.open-meteo.com" in str(request.url)
        assert "customer" not in str(request.url)
        assert request.url.params.get("apikey") is None
        return httpx.Response(200, json=_ARCHIVE_PAYLOAD)

    provider = OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        api_key="test-key-123",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.get_recent_rainfall(-21.1775, -47.8103, days=2)


async def test_with_a_model_configured_forecast_calls_request_that_model() -> None:
    """Item ADR-0075: an explicit model (e.g. ECMWF IFS) replaces
    Open-Meteo's own opaque "best_match" blend for forecast/current calls."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["models"] = request.url.params.get("models")
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        model="ecmwf_ifs025",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.get_forecast(-21.1775, -47.8103)

    assert captured["models"] == "ecmwf_ifs025"


async def test_without_a_model_configured_no_models_param_is_sent() -> None:
    """`model=None` must keep the previous default behavior (Open-Meteo's
    own best_match) — never silently send an empty `models=` param."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "models" not in request.url.params
        return httpx.Response(200, json=_FORECAST_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    await provider.get_forecast(-21.1775, -47.8103)


async def test_a_model_never_reaches_the_archive_host() -> None:
    """The archive/historical endpoint is an ERA5 reanalysis product —
    live model selection doesn't apply there, so `get_recent_rainfall`
    must never send a `models=` param even when one is configured."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "models" not in request.url.params
        return httpx.Response(200, json=_ARCHIVE_PAYLOAD)

    provider = OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        model="ecmwf_ifs025",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.get_recent_rainfall(-21.1775, -47.8103, days=2)


# ---------------------------------------------------------------------------
# Fase 2 — comparação e validação de previsões (get_multi_model_forecast)
# ---------------------------------------------------------------------------


async def test_multi_model_forecast_requests_comma_joined_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["models"] == "ecmwf_ifs025,gfs_seamless"
        return httpx.Response(200, json=_MULTI_MODEL_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    result = await provider.get_multi_model_forecast(
        -21.1775, -47.8103, models=["ecmwf_ifs025", "gfs_seamless"]
    )
    assert set(result.keys()) == {"ecmwf_ifs025", "gfs_seamless"}


async def test_multi_model_forecast_parses_suffixed_keys_per_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MULTI_MODEL_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    result = await provider.get_multi_model_forecast(
        -21.1775, -47.8103, models=["ecmwf_ifs025", "gfs_seamless"]
    )

    ecmwf_day0 = result["ecmwf_ifs025"][0]
    assert ecmwf_day0 == ModelDailyPoint(
        day=date(2026, 9, 5),
        model="ecmwf_ifs025",
        temperature_max_c=31.1,
        precipitation_mm=2.40,
        precipitation_probability_percent=20,
        wind_gusts_max_kmh=25.0,
    )
    gfs_day1 = result["gfs_seamless"][1]
    assert gfs_day1.temperature_max_c == 23.6
    assert gfs_day1.precipitation_mm == 9.30


async def test_multi_model_forecast_missing_model_degrades_to_none_fields() -> None:
    """A model requested but absent from the response (e.g. Open-Meteo
    dropped it, or a typo) still gets one point per day — same day range as
    every other model, so callers can zip by index across models — but with
    every field `None`, never a crash and never silently invented data for
    the missing model."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MULTI_MODEL_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    result = await provider.get_multi_model_forecast(
        -21.1775, -47.8103, models=["ecmwf_ifs025", "icon_seamless"]
    )
    assert len(result["icon_seamless"]) == 3
    assert all(p.temperature_max_c is None for p in result["icon_seamless"])
    assert len(result["ecmwf_ifs025"]) == 3


async def test_multi_model_forecast_raises_on_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"latitude": -21.1775})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_multi_model_forecast(-21.1775, -47.8103, models=["ecmwf_ifs025"])


# ---------------------------------------------------------------------------
# Fase 2 — ground truth for scoring models (get_daily_observations)
# ---------------------------------------------------------------------------

_OBSERVATIONS_PAYLOAD = {
    "latitude": -21.19508,
    "longitude": -47.79248,
    "daily": {
        "time": ["2026-08-28", "2026-08-29"],
        "temperature_2m_max": [32.6, 34.5],
        "precipitation_sum": [0.0, 3.2],
        "wind_gusts_10m_max": [33.8, 40.7],
    },
}


async def test_daily_observations_parses_all_three_variables() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OBSERVATIONS_PAYLOAD)

    provider = _make_provider(httpx.MockTransport(handler))
    result = await provider.get_daily_observations(
        -21.1775, -47.8103, start_date=date(2026, 8, 28), end_date=date(2026, 8, 29)
    )
    assert result == [
        ObservedDailyPoint(
            day=date(2026, 8, 28),
            temperature_max_c=32.6,
            precipitation_mm=0.0,
            wind_gusts_max_kmh=33.8,
        ),
        ObservedDailyPoint(
            day=date(2026, 8, 29),
            temperature_max_c=34.5,
            precipitation_mm=3.2,
            wind_gusts_max_kmh=40.7,
        ),
    ]


async def test_daily_observations_never_sends_a_models_param() -> None:
    """Ground truth is model-independent by definition — a `models=` param
    here would be a contradiction in terms."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "models" not in request.url.params
        return httpx.Response(200, json=_OBSERVATIONS_PAYLOAD)

    provider = OpenMeteoWeatherProvider(
        forecast_url="https://api.open-meteo.com/v1/forecast",
        archive_url="https://archive-api.open-meteo.com/v1/archive",
        model="ecmwf_ifs025",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await provider.get_daily_observations(
        -21.1775, -47.8103, start_date=date(2026, 8, 28), end_date=date(2026, 8, 29)
    )


async def test_daily_observations_raises_on_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"latitude": -21.1775})

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_daily_observations(
            -21.1775, -47.8103, start_date=date(2026, 8, 28), end_date=date(2026, 8, 29)
        )
