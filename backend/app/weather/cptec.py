"""CptecWeatherProvider — INPE/CPTEC's public forecast XML service.

Used as an automatic fallback when the primary provider (INMET) is
unavailable — see ``FallbackWeatherProvider`` and ADR-0011. INMET has proven
unstable in production; CPTEC is a second, independently-operated INPE
service with a materially different failure mode.

Endpoint confirmed live: ``GET {base_url}/cidade/7dias/{lat}/{lon}/
previsaoLatLon.xml`` — no API key, no geocode resolution needed (unlike
INMET's forecast endpoint, which requires an IBGE municipality geocode).
Despite the "7dias" name, it returns **6** ``<previsao>`` days in practice
(verified live) — not asserted as 7 here, honest about what was observed.

Response shape (verified live for Ribeirão Preto, 2026-08-19):

.. code-block:: xml

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
      ...
    </cidade>

``tempo`` is a short condition code (e.g. ``"pn"`` = "poucas nuvens") — not
decoded into a probability or mm here, since this provider gives no numeric
precipitation figure. ``maxima`` is used as the day's representative
temperature (same convention as ``InmetWeatherProvider.get_forecast``,
which uses the "tarde" period's ``temp_max``).

CPTEC's current-conditions endpoint only covers capital cities, not
arbitrary lat/lon — ``get_current_data`` honestly reports unavailable
rather than approximating from a capital far away. Likewise, this service
has no radar/cell data or official warnings — ``get_radar_frames`` and
``get_warnings`` are unavailable here too. CPTEC's real strength (and the
reason it exists in this codebase) is the forecast.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from xml.etree import ElementTree

import httpx

from app.core.enums import WeatherSourceKind
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    ForecastPoint,
    Provenance,
    RadarFrameData,
    RainfallHistory,
    Warning,
    WeatherProvider,
)
from app.weather.provider import (
    WeatherProviderUnavailableError as _BaseWeatherProviderUnavailableError,
)

_PROVIDER_NAME = "INPE/CPTEC"


class WeatherProviderUnavailableError(_BaseWeatherProviderUnavailableError):
    """Raised when CPTEC data cannot be honestly produced for a request."""


def _text(element: ElementTree.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _as_float(element: ElementTree.Element, tag: str) -> float | None:
    value = _text(element, tag)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class CptecWeatherProvider(WeatherProvider):
    """Forecast-only weather source backed by INPE/CPTEC's public XML API."""

    def __init__(
        self,
        *,
        base_url: str,
        http_timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=http_timeout_seconds)

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.FORECAST_MODEL

    def _provenance(self) -> Provenance:
        return Provenance(source_name=_PROVIDER_NAME, source_kind=self.kind, is_mock=False)

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        raise WeatherProviderUnavailableError(
            "CPTEC's public XML service only has current-conditions data for "
            "capital cities, not arbitrary coordinates — refusing to "
            "approximate from a distant capital."
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        raise WeatherProviderUnavailableError(
            "CPTEC's public XML service has no radar/cell reflectivity data."
        )

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        raise WeatherProviderUnavailableError(
            "CPTEC's public XML service has no official-warnings feed."
        )

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        url = f"{self._base_url}/cidade/7dias/{latitude}/{longitude}/previsaoLatLon.xml"
        response = await self._client.get(url)
        response.raise_for_status()
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise WeatherProviderUnavailableError(
                "Unexpected CPTEC previsaoLatLon.xml response shape."
            ) from exc
        if root.tag != "cidade":
            raise WeatherProviderUnavailableError(
                "Unexpected CPTEC previsaoLatLon.xml response shape."
            )

        points: list[ForecastPoint] = []
        for previsao in root.findall("previsao"):
            dia = _text(previsao, "dia")
            if dia is None:
                continue
            try:
                day: date = datetime.strptime(dia, "%Y-%m-%d").date()
            except ValueError:
                continue
            points.append(
                ForecastPoint(
                    time=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                    temperature_c=_as_float(previsao, "maxima"),
                    temperature_min_c=_as_float(previsao, "minima"),
                    # CPTEC's "tempo" is a condition code (e.g. "pn"), not a
                    # numeric probability or mm — left unset rather than
                    # invented from a code.
                    precipitation_probability=None,
                    precipitation_mm=None,
                )
            )

        return Forecast(
            provenance=self._provenance(),
            latitude=latitude,
            longitude=longitude,
            points=points,
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        raise WeatherProviderUnavailableError(
            "CPTEC's public XML service has no historical rainfall data, only forecasts."
        )

    async def aclose(self) -> None:
        await self._client.aclose()
