"""Tests for InmetWeatherProvider — the real (FASE 13) weather source.

Network calls are faked with ``httpx.MockTransport`` (no live requests, no
extra dependency) so the mapping from INMET's field names to our DTOs is
verified deterministically.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.enums import WeatherSourceKind
from app.weather.inmet import (
    InmetWeatherProvider,
    WeatherProviderUnavailableError,
    marshall_palmer_dbz,
)

_STATIONS = [
    {
        "CD_ESTACAO": "A701",
        "VL_LATITUDE": "-23.5",
        "VL_LONGITUDE": "-46.6",
        "UF": "SP",
        "DC_NOME": "São Paulo",
    },
    {
        "CD_ESTACAO": "A999",
        "VL_LATITUDE": "0.0",
        "VL_LONGITUDE": "0.0",
        "UF": "XX",
        "DC_NOME": "Nowhereland",
    },
]

_MUNICIPIOS_SP = [
    {"id": "3550308", "nome": "São Paulo"},
    {"id": "3509502", "nome": "Campinas"},
]

_PREVISAO_3550308 = {
    "3550308": {
        "20/08/2026": {
            "manha": {"temp_max": 25, "temp_min": 14, "resumo": "Poucas nuvens"},
            "tarde": {"temp_max": 27, "temp_min": 14, "resumo": "Poucas nuvens"},
            "noite": {"temp_max": 20, "temp_min": 14, "resumo": "Céu limpo"},
        },
        "21/08/2026": {
            "tarde": {"temp_max": 22, "temp_min": 13, "resumo": "Muitas nuvens"},
        },
    }
}

_TODAY = datetime.now(UTC).date().isoformat()
_HOUR = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
_HOUR_STR = _HOUR.strftime("%H%M")

_READINGS_A701 = [
    {
        "CD_ESTACAO": "A701",
        "DT_MEDICAO": _TODAY,
        "HR_MEDICAO": _HOUR_STR,
        "TEM_INS": "24.3",
        "VEN_VEL": "5.0",
        "VEN_RAJ": "12.0",
        "VEN_DIR": "220",
        "CHUVA": "8.0",
    }
]

_AVISOS = [
    {
        "estados": "SP, RJ",
        "tipo": "chuva_intensa",
        "severidade": "orange",
        "descricao": "Chuva intensa prevista.",
        "data_inicio": datetime.now(UTC).isoformat(),
    },
    {
        "estados": "AM",
        "tipo": "seca",
        "severidade": "yellow",
        "descricao": "Aviso não relacionado ao estado consultado.",
    },
]


_VALID_TOKEN = "valid-token-123"


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/estacoes/T":
        return httpx.Response(200, json=_STATIONS)
    if path.startswith("/token/estacao/") and path.endswith(f"/A701/{_VALID_TOKEN}"):
        return httpx.Response(200, json=_READINGS_A701)
    if path.startswith("/token/estacao/"):
        # INMET's real behavior for a bad/expired token: 200 OK, plain text,
        # not JSON — never a 401/403 (confirmed live, ADR-0080).
        return httpx.Response(200, text="CHAVE INVÁLIDA!")
    if path.startswith("/estacao/") and path.endswith("/A701"):
        return httpx.Response(200, json=_READINGS_A701)
    if path.startswith("/estacao/") and path.endswith("/A999"):
        return httpx.Response(200, json=[])
    if path == "/avisos/ativos":
        return httpx.Response(200, json=_AVISOS)
    if path == "/ibge/estados/SP/municipios":
        return httpx.Response(200, json=_MUNICIPIOS_SP)
    if path == "/ibge/estados/XX/municipios":
        return httpx.Response(200, json=[])
    if path == "/previsao/3550308":
        return httpx.Response(200, json=_PREVISAO_3550308)
    return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def provider() -> InmetWeatherProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="http://test")
    return InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        previsao_url="http://test",
        ibge_localidades_url="http://test/ibge",
        min_rain_rate_mm_h=4.0,
        max_station_distance_km=100.0,
        client=client,
    )


async def test_current_data_maps_nearest_station_fields(provider: InmetWeatherProvider) -> None:
    data = await provider.get_current_data(-23.5, -46.6)
    assert data.provenance.is_mock is False
    assert data.provenance.source_kind is WeatherSourceKind.STATION
    assert data.temperature_c == 24.3
    assert data.wind_kmh == pytest.approx(18.0)  # 5.0 m/s -> km/h
    assert data.wind_gusts_kmh == pytest.approx(43.2)
    assert data.wind_direction_deg == pytest.approx(220.0)
    assert data.precipitation_mm == 8.0


async def test_uses_the_token_endpoint_when_api_token_is_configured() -> None:
    """ADR-0080: the public readings route is retired — with a token
    configured, reads must go through /token/estacao/.../{token} instead."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="http://test")
    provider = InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        previsao_url="http://test",
        ibge_localidades_url="http://test/ibge",
        api_token=_VALID_TOKEN,
        min_rain_rate_mm_h=4.0,
        max_station_distance_km=100.0,
        client=client,
    )
    data = await provider.get_current_data(-23.5, -46.6)
    assert data.temperature_c == 24.3


async def test_an_invalid_token_raises_a_clear_error_not_a_generic_one() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="http://test")
    provider = InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        previsao_url="http://test",
        ibge_localidades_url="http://test/ibge",
        api_token="wrong-token",
        min_rain_rate_mm_h=4.0,
        max_station_distance_km=100.0,
        client=client,
    )
    with pytest.raises(WeatherProviderUnavailableError, match="rejected the configured API token"):
        await provider.get_current_data(-23.5, -46.6)


async def test_current_data_raises_when_no_station_nearby(provider: InmetWeatherProvider) -> None:
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_current_data(60.0, 60.0)


async def test_radar_frames_estimate_reflectivity_from_rain_rate(
    provider: InmetWeatherProvider,
) -> None:
    frames = await provider.get_radar_frames(limit=1)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.provenance.is_mock is False
    assert len(frame.cells) == 1
    cell = frame.cells[0]
    assert cell.latitude == -23.5
    assert cell.max_reflectivity == pytest.approx(marshall_palmer_dbz(8.0), abs=0.1)
    assert cell.area_km2 is None


async def test_radar_frames_skip_cells_below_rain_threshold(provider: InmetWeatherProvider) -> None:
    provider2 = InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        min_rain_rate_mm_h=50.0,
        client=provider._client,  # noqa: SLF001 (reuse fixture's mock transport)
    )
    frames = await provider2.get_radar_frames(limit=1)
    assert frames[0].cells == []


async def test_warnings_are_matched_by_nearest_station_state(
    provider: InmetWeatherProvider,
) -> None:
    warnings = await provider.get_warnings(-23.5, -46.6)
    assert len(warnings) == 1
    assert warnings[0].kind == "chuva_intensa"
    assert warnings[0].provenance.source_kind is WeatherSourceKind.OFFICIAL_WARNING
    assert warnings[0].provenance.is_mock is False


async def test_forecast_includes_real_inmet_days_plus_yesterday(
    provider: InmetWeatherProvider,
) -> None:
    forecast = await provider.get_forecast(-23.5, -46.6)
    assert forecast.provenance.is_mock is False
    # 1 historical (yesterday, from the station) + 2 real forecast days.
    assert len(forecast.points) == 3
    # The forecast-derived points use the "tarde" period's temp_max/temp_min.
    forecast_temps = {p.temperature_c for p in forecast.points[1:]}
    assert forecast_temps == {27.0, 22.0}
    forecast_min_temps = {p.temperature_min_c for p in forecast.points[1:]}
    assert forecast_min_temps == {14.0, 13.0}
    # No fabricated precipitation numbers from INMET's free-text summary.
    assert all(p.precipitation_probability is None for p in forecast.points[1:])
    assert all(p.precipitation_mm is None for p in forecast.points[1:])


async def test_forecast_raises_when_municipality_not_found_in_ibge(
    provider: InmetWeatherProvider,
) -> None:
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_forecast(0.0, 0.0)  # nearest station has UF "XX", no IBGE match


async def test_recent_rainfall_sums_daily_readings(provider: InmetWeatherProvider) -> None:
    rainfall = await provider.get_recent_rainfall(-23.5, -46.6, days=3)
    assert rainfall.provenance.is_mock is False
    assert len(rainfall.daily) == 3
    # The fixture handler serves the same single reading (CHUVA=8.0) for
    # any requested day, so each day's total is that one reading's value.
    assert all(d.total_mm == 8.0 for d in rainfall.daily)


async def test_recent_rainfall_raises_when_no_station_nearby(
    provider: InmetWeatherProvider,
) -> None:
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_recent_rainfall(60.0, 60.0, days=5)


def test_marshall_palmer_dbz_is_zero_for_no_rain() -> None:
    assert marshall_palmer_dbz(0.0) == 0.0


def test_marshall_palmer_dbz_increases_with_rain_rate() -> None:
    assert marshall_palmer_dbz(20.0) > marshall_palmer_dbz(5.0)


def test_default_client_sends_a_browser_like_user_agent() -> None:
    """Real production incident (2026-09-01): every INMET endpoint reset
    the connection specifically for httpx's own default User-Agent
    (`python-httpx/x.y.z`) — confirmed live from two different networks —
    while an ordinary browser User-Agent succeeded immediately. This was a
    WAF/bot-protection fingerprinting the generic client string, not INMET
    actually being down, and it silently broke the one feature with no
    fallback (storm cells) for an unknown stretch of time."""
    provider = InmetWeatherProvider(base_url="http://test", avisos_url="http://test")
    user_agent = provider._client.headers.get("user-agent")  # noqa: SLF001
    assert user_agent is not None
    assert "python-httpx" not in user_agent
    assert "Mozilla" in user_agent


async def test_fetch_stations_raises_cleanly_on_a_non_json_body() -> None:
    """A second real production bug found live alongside the User-Agent
    one: INMET can answer 200 with an empty (non-JSON) body — `.json()`
    then raises `json.JSONDecodeError` (a `ValueError`, not
    `httpx.HTTPError`), which used to propagate uncaught out of this
    method instead of degrading the same honest way a bad-shape response
    already did."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    provider = InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    with pytest.raises(WeatherProviderUnavailableError):
        await provider._fetch_stations()  # noqa: SLF001


async def test_one_stations_non_json_reading_never_crashes_the_whole_radar_fetch() -> None:
    """The exact real bug: one station (A999) returning a non-JSON body
    for its readings used to raise `json.JSONDecodeError` straight out of
    `_fetch_station_readings`, which `get_radar_frames`'s own per-station
    try/except never expected (it only caught `httpx.HTTPError`/
    `WeatherProviderUnavailableError`) — crashing the *entire* cycle over
    one misbehaving station instead of just skipping it, same spirit as
    `test_radar_frames_skip_cells_below_rain_threshold`."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/estacoes/T":
            return httpx.Response(200, json=_STATIONS)
        if path.startswith("/estacao/") and path.endswith("/A701"):
            return httpx.Response(200, json=_READINGS_A701)
        if path.startswith("/estacao/") and path.endswith("/A999"):
            return httpx.Response(200, content=b"")  # the misbehaving station
        return httpx.Response(404, json={"detail": "not found"})

    provider = InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
        min_rain_rate_mm_h=4.0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    frames = await provider.get_radar_frames(limit=1)
    assert len(frames) == 1
    assert len(frames[0].cells) == 1  # A701's real reading still came through
