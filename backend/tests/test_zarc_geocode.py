"""Tests for the ZARC município geocode resolver (item ZARC, ADR-0069).

Same ``httpx.MockTransport`` pattern as ``test_weather_inmet.py`` — no
live INMET/IBGE calls.
"""

from __future__ import annotations

import httpx
import pytest

from app.zarc.geocode import MunicipioNotResolvedError, resolve_municipio_geocode

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


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/estacoes/T":
        return httpx.Response(200, json=_STATIONS)
    if path == "/estados/SP/municipios":
        return httpx.Response(200, json=_MUNICIPIOS_SP)
    if path == "/estados/XX/municipios":
        return httpx.Response(200, json=[])
    return httpx.Response(404, json={"detail": "not found"})


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="http://test")


async def test_resolves_the_geocode_of_the_nearest_station_municipio() -> None:
    geocode = await resolve_municipio_geocode(
        -23.55,
        -46.63,
        inmet_base_url="http://test",
        ibge_localidades_url="http://test",
        client=_client(),
    )
    assert geocode == "3550308"


async def test_raises_when_no_station_is_close_enough() -> None:
    with pytest.raises(MunicipioNotResolvedError):
        await resolve_municipio_geocode(
            10.0,
            10.0,
            inmet_base_url="http://test",
            ibge_localidades_url="http://test",
            max_station_distance_km=1.0,
            client=_client(),
        )


async def test_raises_when_no_municipio_name_matches() -> None:
    with pytest.raises(MunicipioNotResolvedError):
        await resolve_municipio_geocode(
            0.0,
            0.0,
            inmet_base_url="http://test",
            ibge_localidades_url="http://test",
            client=_client(),
        )


def _unreachable_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadError("connection reset by peer")


async def test_wraps_a_network_failure_instead_of_raising_the_raw_httpx_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_unreachable_handler), base_url="http://test"
    )
    with pytest.raises(MunicipioNotResolvedError):
        await resolve_municipio_geocode(
            -23.55,
            -46.63,
            inmet_base_url="http://test",
            ibge_localidades_url="http://test",
            client=client,
        )
