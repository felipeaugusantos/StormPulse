"""Tests for CptecWeatherProvider — the INPE/CPTEC forecast source (FASE 17).

Network calls are faked with ``httpx.MockTransport`` (no live requests) —
the fixture XML mirrors the real response verified live for Ribeirão Preto
on 2026-08-19 via ``previsaoLatLon.xml``.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.enums import WeatherSourceKind
from app.weather.cptec import CptecWeatherProvider, WeatherProviderUnavailableError

_PREVISAO_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<cidade>
<nome>Ribeirão Preto</nome>
<uf>SP</uf>
<atualizacao>2026-08-19</atualizacao>
<previsao>
<dia>2026-08-20</dia>
<tempo>pn</tempo>
<maxima>32</maxima>
<minima>16</minima>
<iuv>0.0</iuv>
</previsao>
<previsao>
<dia>2026-08-21</dia>
<tempo>pn</tempo>
<maxima>29</maxima>
<minima>16</minima>
<iuv>0.0</iuv>
</previsao>
</cidade>
"""


def _make_provider(transport: httpx.MockTransport) -> CptecWeatherProvider:
    return CptecWeatherProvider(
        base_url="https://servicos.cptec.inpe.br/XML",
        client=httpx.AsyncClient(transport=transport),
    )


async def test_get_forecast_parses_previsao_days() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "previsaoLatLon.xml" in str(request.url)
        return httpx.Response(200, text=_PREVISAO_XML)

    provider = _make_provider(httpx.MockTransport(handler))
    forecast = await provider.get_forecast(-21.1775, -47.8103)

    assert forecast.provenance.source_name == "INPE/CPTEC"
    assert forecast.provenance.source_kind == WeatherSourceKind.FORECAST_MODEL
    assert forecast.provenance.is_mock is False
    assert len(forecast.points) == 2
    assert forecast.points[0].temperature_c == 32.0
    assert forecast.points[0].precipitation_mm is None
    assert forecast.points[1].temperature_c == 29.0


async def test_get_forecast_raises_on_malformed_xml() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not xml at all <<<")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_forecast(-21.1775, -47.8103)


async def test_get_forecast_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    provider = _make_provider(httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_forecast(-21.1775, -47.8103)


async def test_current_data_and_radar_and_warnings_are_honestly_unavailable() -> None:
    provider = _make_provider(httpx.MockTransport(lambda request: httpx.Response(200)))
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_current_data(-21.1775, -47.8103)
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_radar_frames()
    with pytest.raises(WeatherProviderUnavailableError):
        await provider.get_warnings(-21.1775, -47.8103)
