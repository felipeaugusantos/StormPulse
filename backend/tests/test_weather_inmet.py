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
    },
    {
        "CD_ESTACAO": "A999",
        "VL_LATITUDE": "0.0",
        "VL_LONGITUDE": "0.0",
        "UF": "XX",
    },
]

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


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/estacoes/T":
        return httpx.Response(200, json=_STATIONS)
    if path.startswith("/estacao/") and path.endswith("/A701"):
        return httpx.Response(200, json=_READINGS_A701)
    if path.startswith("/estacao/") and path.endswith("/A999"):
        return httpx.Response(200, json=[])
    if path == "/avisos/ativos":
        return httpx.Response(200, json=_AVISOS)
    return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def provider() -> InmetWeatherProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="http://test")
    return InmetWeatherProvider(
        base_url="http://test",
        avisos_url="http://test",
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
    assert data.precipitation_mm == 8.0


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


async def test_forecast_has_no_fabricated_points(provider: InmetWeatherProvider) -> None:
    forecast = await provider.get_forecast(-23.5, -46.6)
    assert forecast.provenance.is_mock is False
    assert forecast.points == []


def test_marshall_palmer_dbz_is_zero_for_no_rain() -> None:
    assert marshall_palmer_dbz(0.0) == 0.0


def test_marshall_palmer_dbz_increases_with_rain_rate() -> None:
    assert marshall_palmer_dbz(20.0) > marshall_palmer_dbz(5.0)
