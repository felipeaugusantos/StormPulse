"""NasaPowerSoilMoistureProvider — real soil-wetness lookup against NASA's
POWER API (item NASA).

`GET https://power.larc.nasa.gov/api/temporal/daily/point` — confirmed live
(2026-08-28) for a real StormPulse coordinate (-21.18, -47.81): no API key,
no login, `community=AG` (agriculture), parameters `GWETTOP`/`GWETROOT`/
`GWETPROF` (Surface/Root Zone/Profile Soil Wetness, unitless fraction of
saturation 0-1 — converted to a 0-100 percentage here). NASA's own data
policy allows any use, commercial or non-commercial, with no attribution
requirement — unlike Google Earth Engine (whose free tier is restricted to
nonprofit/academic/government use and explicitly excludes "fee-for-service"
commercial products), which is why this was chosen over accessing SMAP
itself through Earth Engine.

The most recent 1-2 days routinely come back as the fill value `-999.0`
(the underlying GEOS model run hasn't finished processing yet) — same
"walk backwards to the newest usable value" idiom already used for NDVI's
interval selection (`app/ndvi/sentinel_hub.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.enums import WeatherSourceKind
from app.soilmoisture.provider import (
    SoilMoistureObservation,
    SoilMoistureProvider,
    SoilMoistureProviderUnavailableError,
)
from app.weather.provider import Provenance

_PROVIDER_NAME = "NASA POWER"
_FILL_VALUE = -999.0
_LOOKBACK_DAYS = 10


class NasaPowerSoilMoistureProvider(SoilMoistureProvider):
    def __init__(
        self,
        *,
        base_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point",
        http_timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=http_timeout_seconds)

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def get_soil_moisture(self, latitude: float, longitude: float) -> SoilMoistureObservation:
        end = datetime.now(UTC).date()
        start = end - timedelta(days=_LOOKBACK_DAYS)
        try:
            response = await self._client.get(
                self._base_url,
                params={
                    "parameters": "GWETTOP,GWETROOT,GWETPROF",
                    "community": "AG",
                    "longitude": longitude,
                    "latitude": latitude,
                    "start": start.strftime("%Y%m%d"),
                    "end": end.strftime("%Y%m%d"),
                    "format": "JSON",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise SoilMoistureProviderUnavailableError(
                "Falha ao consultar a NASA POWER API"
            ) from exc

        try:
            series: dict[str, dict[str, Any]] = payload["properties"]["parameter"]
            top, root, prof = series["GWETTOP"], series["GWETROOT"], series["GWETPROF"]
        except (KeyError, TypeError) as exc:
            raise SoilMoistureProviderUnavailableError(
                "Resposta inesperada da NASA POWER API"
            ) from exc

        # Chronologically ordered keys (YYYYMMDD strings sort correctly as
        # text) — walk backwards for the newest day with all three values
        # actually populated, same idiom as NDVI's interval selection.
        for day_str in sorted(top.keys(), reverse=True):
            top_v, root_v, prof_v = top.get(day_str), root.get(day_str), prof.get(day_str)
            if (
                top_v is None
                or root_v is None
                or prof_v is None
                or top_v == _FILL_VALUE
                or root_v == _FILL_VALUE
                or prof_v == _FILL_VALUE
            ):
                continue
            observed_at = datetime.strptime(day_str, "%Y%m%d").date()
            return SoilMoistureObservation(
                provenance=Provenance(
                    source_name=_PROVIDER_NAME,
                    source_kind=WeatherSourceKind.FORECAST_MODEL,
                    is_mock=False,
                ),
                observed_at=observed_at,
                surface_wetness_percent=round(float(top_v) * 100, 1),
                root_zone_wetness_percent=round(float(root_v) * 100, 1),
                profile_wetness_percent=round(float(prof_v) * 100, 1),
            )

        raise SoilMoistureProviderUnavailableError(
            f"Nenhum dado de umidade do solo disponível nos últimos {_LOOKBACK_DAYS} dias"
        )
