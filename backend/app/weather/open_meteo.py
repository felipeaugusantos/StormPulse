"""OpenMeteoWeatherProvider — Open-Meteo weather models, third fallback
tier (FASE 20).

**Real production incident (2026-08-28, ADR-0074)**: the free/anonymous
tier is documented as non-commercial-use-only and shares a per-IP rate
limit across every anonymous caller — StormPulse's production IP got
throttled specifically on the forecast endpoint (`get_current_data`/
`get_forecast`, both backed by the same call) for a sustained period,
while the archive endpoint (lower volume) kept working. Fixed by
subscribing to Open-Meteo's paid "Standard" commercial plan: when
`api_key` is set, forecast calls are routed to the dedicated
`customer-api.open-meteo.com` host with the key attached, per Open-Meteo's
own onboarding instructions — no more shared IP, no more rate limit within
the plan's monthly budget. The archive/historical endpoint is deliberately
**not** switched to the customer host or given the key: the Standard plan
explicitly does not include the historical weather API (Professional
does) — attaching a key there would very likely 403 rather than succeed,
so `get_recent_rainfall` keeps using the free public archive host exactly
as before.

**Explicit model instead of opaque auto-selection (ADR-0075)**: Open-Meteo
blends several national weather models (GFS/NOAA, ICON/DWD, ECMWF IFS,
among others) behind a `best_match` heuristic that isn't documented for
South America specifically (it's a global catch-all: "ECMWF IFS, GFS, or
ICON Global"). ECMWF's IFS became free for any use — including commercial
— under CC-BY-4.0 in 2025, and Open-Meteo exposes it directly via
`models=ecmwf_ifs025`. Confirmed live (2026-08-29) that every field this
provider requests (current conditions, CAPE, ET0, humidity, gust maxima)
is available under that model, at values in the same range as
`best_match`'s. `model` (default `"ecmwf_ifs025"`) picks a known, citable,
consistently-sourced model instead of an opaque blend — never applied to
the archive/historical endpoint (an ERA5 reanalysis product, unrelated to
live model selection).

Third redundancy tier, behind INMET and INPE/CPTEC — see
``FallbackWeatherProvider`` and ADR-0015. Unlike INMET/CPTEC, this
genuinely gives **numeric** precipitation
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

from dataclasses import dataclass
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


_CUSTOMER_FORECAST_HOST = "https://customer-api.open-meteo.com"
_PUBLIC_FORECAST_HOST = "https://api.open-meteo.com"


@dataclass(frozen=True)
class ObservedDailyPoint:
    """One day's *observed* (not forecast) weather, from the archive/ERA5
    reanalysis endpoint — Fase 2's ground truth for scoring the forecast
    models. ERA5 reanalysis assimilates real global observations after the
    fact; it is not the same product as the live forecast models being
    scored, but it is the most complete, honestly-available "what actually
    happened" source today (INMET's own station-reading endpoint is retired
    without a token, ADR-0080) — same archive host/product already trusted
    elsewhere in this codebase for historical rainfall
    (``RainfallHistory``/``get_recent_rainfall``)."""

    day: date
    temperature_max_c: float | None
    precipitation_mm: float | None
    wind_gusts_max_kmh: float | None


@dataclass(frozen=True)
class ModelDailyPoint:
    """One day's forecast from one specific model — Fase 2 (Comparação e
    Validação de Previsões). Deliberately narrower than ``ForecastPoint``:
    only the variables the comparison engine (``engine/validation.py``)
    actually scores (temperature, precipitation amount/probability, wind
    gusts), not every field a single-model forecast carries."""

    day: date
    model: str
    temperature_max_c: float | None
    precipitation_mm: float | None
    precipitation_probability_percent: float | None
    wind_gusts_max_kmh: float | None


class OpenMeteoWeatherProvider(WeatherProvider):
    """Third-tier real weather source backed by Open-Meteo's API."""

    def __init__(
        self,
        *,
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
        archive_url: str = "https://archive-api.open-meteo.com/v1/archive",
        api_key: str | None = None,
        model: str | None = None,
        http_timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Only the forecast host has a paid/commercial tier we're actually
        # subscribed to (see module docstring) — swap it to the dedicated
        # customer host when a key is configured; the archive host is left
        # untouched no matter what, since our plan doesn't cover it.
        self._forecast_url = (
            forecast_url.replace(_PUBLIC_FORECAST_HOST, _CUSTOMER_FORECAST_HOST, 1)
            if api_key
            else forecast_url
        )
        self._archive_url = archive_url
        self._api_key = api_key
        # `None` keeps Open-Meteo's own opaque "best_match" auto-selection
        # (see module docstring for why an explicit model is preferred —
        # ADR-0075). Never applied to the archive/historical endpoint: that's
        # an ERA5 reanalysis product, unrelated to live model selection.
        self._model = model
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
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
                "precipitation,relative_humidity_2m"
            ),
            "daily": (
                "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                "precipitation_sum,precipitation_probability_max,"
                "relative_humidity_2m_mean,relative_humidity_2m_max,"
                "wind_gusts_10m_max,et0_fao_evapotranspiration,cape_max"
            ),
            "timezone": "UTC",
        }
        if self._model:
            params["models"] = self._model
        if self._api_key:
            params["apikey"] = self._api_key
        response = await self._client.get(self._forecast_url, params=params)
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
            wind_direction_deg=current.get("wind_direction_10m"),
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

    async def get_multi_model_forecast(
        self, latitude: float, longitude: float, *, models: list[str], forecast_days: int = 7
    ) -> dict[str, list[ModelDailyPoint]]:
        """Fase 2 (Comparação e Validação de Previsões) — one call, several
        models side by side. Confirmed live (2026-09-05) that Open-Meteo's
        ``models=a,b,c`` suffixes every requested daily variable with
        ``_<model>`` in a single flat ``daily`` dict sharing one ``time``
        array (e.g. ``temperature_2m_max_ecmwf_ifs025``,
        ``temperature_2m_max_gfs_seamless``) — not a nested per-model
        response, so the parsing below reads each suffixed key directly
        rather than expecting a `models` sub-object.

        Independent of ``get_forecast``'s single-model call (`self._model`)
        — this always requests exactly the ``models`` passed in, since a
        comparison needs a fixed known set, not whatever the instance's
        default happens to be. Never applied to the archive/historical
        endpoint (unrelated to live model selection, same reasoning as
        ``_model`` throughout this file).
        """
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": (
                "temperature_2m_max,precipitation_sum,precipitation_probability_max,"
                "wind_gusts_10m_max"
            ),
            "models": ",".join(models),
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
        if self._api_key:
            params["apikey"] = self._api_key
        response = await self._client.get(self._forecast_url, params=params)
        response.raise_for_status()
        data = response.json()
        daily = data.get("daily") if isinstance(data, dict) else None
        if not isinstance(daily, dict):
            raise WeatherProviderUnavailableError(
                "Unexpected Open-Meteo multi-model forecast response shape."
            )

        days_raw = daily.get("time") or []
        try:
            days = [datetime.strptime(d, "%Y-%m-%d").date() for d in days_raw]
        except (ValueError, TypeError) as exc:
            raise WeatherProviderUnavailableError(
                "Unexpected Open-Meteo multi-model 'time' values."
            ) from exc

        result: dict[str, list[ModelDailyPoint]] = {}
        for model in models:
            maxima = daily.get(f"temperature_2m_max_{model}") or []
            precip = daily.get(f"precipitation_sum_{model}") or []
            prob = daily.get(f"precipitation_probability_max_{model}") or []
            gusts = daily.get(f"wind_gusts_10m_max_{model}") or []

            def _at(series: list[Any], i: int) -> Any:
                return series[i] if i < len(series) else None

            result[model] = [
                ModelDailyPoint(
                    day=day,
                    model=model,
                    temperature_max_c=_at(maxima, i),
                    precipitation_mm=_at(precip, i),
                    precipitation_probability_percent=_at(prob, i),
                    wind_gusts_max_kmh=_at(gusts, i),
                )
                for i, day in enumerate(days)
            ]
        return result

    async def get_daily_observations(
        self, latitude: float, longitude: float, *, start_date: date, end_date: date
    ) -> list[ObservedDailyPoint]:
        """Fase 2 (Comparação e Validação de Previsões) — ground truth for
        the days in `[start_date, end_date]`, from the same archive/ERA5
        endpoint `get_recent_rainfall` already uses, just with temperature
        and wind added (see `ObservedDailyPoint` for why this is the ground
        truth chosen). Never applies `self._model`/API key — same reasoning
        as `get_recent_rainfall`."""
        response = await self._client.get(
            self._archive_url,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "temperature_2m_max,precipitation_sum,wind_gusts_10m_max",
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        data = response.json()
        daily = data.get("daily") if isinstance(data, dict) else None
        if not isinstance(daily, dict):
            raise WeatherProviderUnavailableError(
                "Unexpected Open-Meteo archive response shape (daily observations)."
            )

        days_raw = daily.get("time") or []
        maxima = daily.get("temperature_2m_max") or []
        precip = daily.get("precipitation_sum") or []
        gusts = daily.get("wind_gusts_10m_max") or []

        def _at(series: list[Any], i: int) -> Any:
            return series[i] if i < len(series) else None

        points: list[ObservedDailyPoint] = []
        for i, day_str in enumerate(days_raw):
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            points.append(
                ObservedDailyPoint(
                    day=day,
                    temperature_max_c=_at(maxima, i),
                    precipitation_mm=_at(precip, i),
                    wind_gusts_max_kmh=_at(gusts, i),
                )
            )
        return points

    async def aclose(self) -> None:
        await self._client.aclose()
