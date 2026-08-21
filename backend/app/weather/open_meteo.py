"""OpenMeteoWeatherProvider — international, no-key aggregator of national
weather models (FASE 20).

Third redundancy tier, behind INMET and INPE/CPTEC — see
``FallbackWeatherProvider`` and ADR-0015. Free for non-commercial use under
10,000 calls/day (Open-Meteo's terms; StormPulse is well under that), no
API key. Unlike INMET/CPTEC, this genuinely gives **numeric** precipitation
probability and amount in the daily forecast — neither of the other two
sources can (see ADR-0011/0014) — so ``ForecastPoint.precipitation_*`` gets
populated here for the first time, not left ``None``.

Two endpoints confirmed live for Ribeirão Preto (2026-08-20):

- ``GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..
  &current=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,
  relative_humidity_2m
  &daily=temperature_2m_max,temperature_2m_min,temperature_2m_mean,
  precipitation_sum,precipitation_probability_max,
  relative_humidity_2m_mean,relative_humidity_2m_max,wind_gusts_10m_max,
  et0_fao_evapotranspiration,cape_max&timezone=UTC`` — current conditions +
  7-day daily forecast. ``relative_humidity_2m`` feeds the spray-window
  thermal-inversion check (FASE 22, ADR-0018) — calm wind + high humidity
  is the classic dawn-inversion signature that causes spray drift.
  ``cape_max``/``et0_fao_evapotranspiration``/humidity/gust-max daily
  aggregates confirmed live for Ribeirão Preto (2026-08-21) — all free,
  same endpoint, no extra call (FASE 25, ADR-0021): storm instability
  (CAPE, same index REDEMET itself uses alongside K/Totals/Lifted),
  water-balance and disease-risk signals (ET0/humidity), and forecast
  wind gusts (today's gust in ``CurrentConditions`` was already there —
  this is the multi-day version).
- ``GET https://archive-api.open-meteo.com/v1/archive?latitude=..
  &longitude=..&start_date=..&end_date=..&daily=precipitation_sum
  &timezone=UTC`` — historical daily rainfall, any date range (unlike
  INMET, no per-day request loop needed here — one call covers the whole
  window).

No radar/cell reflectivity or official-warnings feed — ``get_radar_frames``
and ``get_warnings`` are honestly unavailable, same reasoning as CPTEC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.enums import WeatherSourceKind
from app.weather.provider import (
    CurrentConditions,
    DailyRainfall,
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

_PROVIDER_NAME = "Open-Meteo"


class WeatherProviderUnavailableError(_BaseWeatherProviderUnavailableError):
    """Raised when Open-Meteo data cannot be honestly produced for a request."""


class OpenMeteoWeatherProvider(WeatherProvider):
    """Third-tier real weather source backed by Open-Meteo's public API."""

    def __init__(
        self,
        *,
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
        archive_url: str = "https://archive-api.open-meteo.com/v1/archive",
        http_timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._forecast_url = forecast_url
        self._archive_url = archive_url
        self._client = client or httpx.AsyncClient(timeout=http_timeout_seconds)

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.FORECAST_MODEL

    def _provenance(self) -> Provenance:
        return Provenance(source_name=_PROVIDER_NAME, source_kind=self.kind, is_mock=False)

    async def _fetch_forecast_payload(self, latitude: float, longitude: float) -> dict[str, Any]:
        response = await self._client.get(
            self._forecast_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,"
                    "relative_humidity_2m"
                ),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                    "precipitation_sum,precipitation_probability_max,"
                    "relative_humidity_2m_mean,relative_humidity_2m_max,"
                    "wind_gusts_10m_max,et0_fao_evapotranspiration,cape_max"
                ),
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise WeatherProviderUnavailableError("Unexpected Open-Meteo forecast response shape.")
        return data

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        data = await self._fetch_forecast_payload(latitude, longitude)
        current = data.get("current")
        if not isinstance(current, dict):
            raise WeatherProviderUnavailableError("Open-Meteo response has no 'current' block.")
        raw_time = current.get("time")
        try:
            observed_at = (
                datetime.fromisoformat(str(raw_time)).replace(tzinfo=UTC)
                if raw_time
                else datetime.now(UTC)
            )
        except ValueError:
            observed_at = datetime.now(UTC)
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=observed_at,
            latitude=latitude,
            longitude=longitude,
            temperature_c=current.get("temperature_2m"),
            wind_kmh=current.get("wind_speed_10m"),
            wind_gusts_kmh=current.get("wind_gusts_10m"),
            precipitation_mm=current.get("precipitation"),
            relative_humidity_percent=current.get("relative_humidity_2m"),
        )

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        raise WeatherProviderUnavailableError("Open-Meteo has no radar/cell reflectivity data.")

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        raise WeatherProviderUnavailableError("Open-Meteo has no official-warnings feed.")

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        data = await self._fetch_forecast_payload(latitude, longitude)
        daily = data.get("daily")
        if not isinstance(daily, dict):
            raise WeatherProviderUnavailableError("Open-Meteo response has no 'daily' block.")

        days = daily.get("time") or []
        maxima = daily.get("temperature_2m_max") or []
        minima = daily.get("temperature_2m_min") or []
        means = daily.get("temperature_2m_mean") or []
        precip_sum = daily.get("precipitation_sum") or []
        precip_prob = daily.get("precipitation_probability_max") or []
        humidity_mean = daily.get("relative_humidity_2m_mean") or []
        humidity_max = daily.get("relative_humidity_2m_max") or []
        gusts_max = daily.get("wind_gusts_10m_max") or []
        et0 = daily.get("et0_fao_evapotranspiration") or []
        cape_max = daily.get("cape_max") or []

        def _at(series: list[Any], i: int) -> Any:
            return series[i] if i < len(series) else None

        points: list[ForecastPoint] = []
        for i, day_str in enumerate(days):
            try:
                day: date = datetime.strptime(day_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            prob = _at(precip_prob, i)
            points.append(
                ForecastPoint(
                    time=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                    temperature_c=_at(maxima, i),
                    temperature_min_c=_at(minima, i),
                    # Unlike INMET/CPTEC, Open-Meteo genuinely gives numeric
                    # precipitation figures — not invented here, read as-is.
                    precipitation_probability=int(prob) if prob is not None else None,
                    precipitation_mm=_at(precip_sum, i),
                    temperature_mean_c=_at(means, i),
                    humidity_mean_percent=_at(humidity_mean, i),
                    humidity_max_percent=_at(humidity_max, i),
                    wind_gusts_max_kmh=_at(gusts_max, i),
                    evapotranspiration_mm=_at(et0, i),
                    cape_max_jkg=_at(cape_max, i),
                )
            )

        return Forecast(
            provenance=self._provenance(), latitude=latitude, longitude=longitude, points=points
        )

    async def get_recent_rainfall(
        self, latitude: float, longitude: float, *, days: int = 15
    ) -> RainfallHistory:
        end_date = datetime.now(UTC).date() - timedelta(days=1)  # yesterday: today may be partial
        start_date = end_date - timedelta(days=days - 1)
        response = await self._client.get(
            self._archive_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "precipitation_sum",
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        data = response.json()
        daily = data.get("daily") if isinstance(data, dict) else None
        if not isinstance(daily, dict):
            raise WeatherProviderUnavailableError("Unexpected Open-Meteo archive response shape.")

        dates = daily.get("time") or []
        totals = daily.get("precipitation_sum") or []
        entries: list[DailyRainfall] = []
        for i, day_str in enumerate(dates):
            if i >= len(totals) or totals[i] is None:
                continue
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            entries.append(DailyRainfall(date=day, total_mm=float(totals[i])))

        return RainfallHistory(
            provenance=self._provenance(), latitude=latitude, longitude=longitude, daily=entries
        )

    async def aclose(self) -> None:
        await self._client.aclose()
