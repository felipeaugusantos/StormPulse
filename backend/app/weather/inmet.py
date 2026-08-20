"""InmetWeatherProvider — real weather source backed by INMET's public API.

Uses the open (no-token) INMET endpoints for automatic weather stations:
``GET /estacoes/T`` (station catalogue) and ``GET /estacao/{inicio}/{fim}/
{codigo}`` (hourly readings). No paid/opaque credential is required for this.

Two honest approximations are made here, both documented in
``docs/adr/0006-integracao-real-inmet.md``:

- **Storm cells** (``get_radar_frames``) are *not* real radar reflectivity —
  INMET's public API does not expose radar mosaics. Cells are derived from
  station rain-gauge rate (mm/h) converted to an estimated equivalent
  reflectivity via the Marshall–Palmer Z-R relation (``Z = 200·R^1.6``).
  This keeps the storm engine's severity classification working end-to-end
  without pretending a rain gauge is a radar.
- **Warnings** (``get_warnings``) are matched to the state (UF) of the
  nearest station, not a precise polygon — INMET's warning feed is keyed by
  IBGE municipality geocode, which we do not resolve from lat/lon here.

``get_forecast`` resolves the nearest station's municipality to an IBGE
geocode (by matching the station's own name against IBGE's public
municipality list for its UF — no third-party geocoder involved) and calls
INMET's real municipal forecast endpoint. That endpoint caps out at **5
days** (today + 4) — verified live, extra path/query parameters are
ignored — so "7 days" isn't honest to promise; a 6th point (yesterday) is
added from the station's own real hourly readings to give a bit of
before/after context. See ADR-0008.
"""

from __future__ import annotations

import math
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.enums import WeatherSourceKind
from app.weather.provider import (
    CurrentConditions,
    Forecast,
    ForecastPoint,
    Provenance,
    RadarFrameData,
    RawCell,
    Warning,
    WeatherProvider,
)
from app.weather.provider import (
    WeatherProviderUnavailableError as _BaseWeatherProviderUnavailableError,
)
from engine.geo import haversine_km

_PROVIDER_NAME = "INMET"

# Candidate field names, defensive against minor schema variations across
# INMET's open-data endpoints (all observed in public documentation/usage).
_LAT_KEYS = ("VL_LATITUDE", "LATITUDE", "vl_latitude")
_LON_KEYS = ("VL_LONGITUDE", "LONGITUDE", "vl_longitude")
_CODE_KEYS = ("CD_ESTACAO", "CD_STATION", "cd_estacao")
_UF_KEYS = ("UF", "SG_ESTADO", "uf")
_NAME_KEYS = ("DC_NOME", "NOME", "dc_nome")
_TEMP_KEYS = ("TEM_INS", "TEMPERATURA", "tem_ins")
_WIND_KEYS = ("VEN_VEL", "VENTO_VELOCIDADE", "ven_vel")
_GUST_KEYS = ("VEN_RAJ", "VENTO_RAJADA", "ven_raj")
_RAIN_KEYS = ("CHUVA", "PRECIPITACAO", "chuva")
_DATE_KEYS = ("DT_MEDICAO", "dt_medicao")
_HOUR_KEYS = ("HR_MEDICAO", "hr_medicao")


def _normalize_name(value: str) -> str:
    """Uppercase, accent-stripped comparison key for municipality names."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.strip().upper()


class WeatherProviderUnavailableError(_BaseWeatherProviderUnavailableError):
    """Raised when INMET data cannot be honestly produced for a request.

    Callers (the ingestion pipeline) must log and skip the cycle — never
    substitute mock data silently under a "real" provenance.
    """


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _as_float(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value = _first(record, keys)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def marshall_palmer_dbz(rain_rate_mm_h: float) -> float:
    """Estimate equivalent radar reflectivity (dBZ) from a rain rate (mm/h).

    Marshall–Palmer Z-R relation: ``Z = 200 * R^1.6`` (Z in mm^6/m^3),
    ``dBZ = 10 * log10(Z)``. A standard meteorological approximation, not a
    measurement — used here because INMET's public API has no radar data.
    """
    rate = max(rain_rate_mm_h, 0.0)
    if rate == 0.0:
        return 0.0
    z = 200.0 * (rate**1.6)
    return 10.0 * math.log10(z)


class InmetWeatherProvider(WeatherProvider):
    """Real weather source backed by INMET's public automatic-station API."""

    def __init__(
        self,
        *,
        base_url: str,
        avisos_url: str,
        previsao_url: str = "https://apiprevmet3.inmet.gov.br",
        ibge_localidades_url: str = "https://servicodados.ibge.gov.br/api/v1/localidades",
        http_timeout_seconds: float = 10.0,
        min_rain_rate_mm_h: float = 4.0,
        max_station_distance_km: float = 100.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._avisos_url = avisos_url.rstrip("/")
        self._previsao_url = previsao_url.rstrip("/")
        self._ibge_localidades_url = ibge_localidades_url.rstrip("/")
        self._min_rain_rate_mm_h = min_rain_rate_mm_h
        self._max_station_distance_km = max_station_distance_km
        self._client = client or httpx.AsyncClient(timeout=http_timeout_seconds)

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    @property
    def kind(self) -> WeatherSourceKind:
        return WeatherSourceKind.STATION

    def _provenance(self, *, kind: WeatherSourceKind | None = None) -> Provenance:
        return Provenance(source_name=_PROVIDER_NAME, source_kind=kind or self.kind, is_mock=False)

    async def _fetch_stations(self) -> list[dict[str, Any]]:
        response = await self._client.get(f"{self._base_url}/estacoes/T")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise WeatherProviderUnavailableError("Unexpected INMET station list response shape.")
        return data

    def _nearest_station(
        self, latitude: float, longitude: float, stations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        best: dict[str, Any] | None = None
        best_distance = math.inf
        for station in stations:
            lat = _as_float(station, _LAT_KEYS)
            lon = _as_float(station, _LON_KEYS)
            if lat is None or lon is None:
                continue
            distance = haversine_km(latitude, longitude, lat, lon)
            if distance < best_distance:
                best, best_distance = station, distance
        if best is None or best_distance > self._max_station_distance_km:
            raise WeatherProviderUnavailableError(
                f"No INMET station within {self._max_station_distance_km} km of "
                f"({latitude}, {longitude})."
            )
        return best

    async def _fetch_station_readings(self, station_code: str, day: date) -> list[dict[str, Any]]:
        iso = day.isoformat()
        response = await self._client.get(f"{self._base_url}/estacao/{iso}/{iso}/{station_code}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise WeatherProviderUnavailableError(
                "Unexpected INMET station readings response shape."
            )
        return data

    def _reading_timestamp(self, reading: dict[str, Any]) -> datetime | None:
        raw_date = _first(reading, _DATE_KEYS)
        raw_hour = _first(reading, _HOUR_KEYS)
        if raw_date is None or raw_hour is None:
            return None
        try:
            hour = int(str(raw_hour).zfill(4)[:2])
            return datetime.fromisoformat(str(raw_date)).replace(hour=hour, tzinfo=UTC)
        except ValueError:
            return None

    async def get_current_data(self, latitude: float, longitude: float) -> CurrentConditions:
        stations = await self._fetch_stations()
        station = self._nearest_station(latitude, longitude, stations)
        code = _first(station, _CODE_KEYS)
        if code is None:
            raise WeatherProviderUnavailableError("Nearest INMET station has no station code.")
        readings = await self._fetch_station_readings(str(code), datetime.now(UTC).date())
        latest = self._latest_reading(readings)
        if latest is None:
            raise WeatherProviderUnavailableError(f"No recent INMET readings for station {code}.")
        observed_at = self._reading_timestamp(latest) or datetime.now(UTC)
        wind_ms = _as_float(latest, _WIND_KEYS)
        gust_ms = _as_float(latest, _GUST_KEYS)
        return CurrentConditions(
            provenance=self._provenance(),
            observed_at=observed_at,
            latitude=latitude,
            longitude=longitude,
            temperature_c=_as_float(latest, _TEMP_KEYS),
            wind_kmh=None if wind_ms is None else round(wind_ms * 3.6, 1),
            wind_gusts_kmh=None if gust_ms is None else round(gust_ms * 3.6, 1),
            precipitation_mm=_as_float(latest, _RAIN_KEYS),
        )

    def _latest_reading(self, readings: list[dict[str, Any]]) -> dict[str, Any] | None:
        timestamped: list[tuple[datetime, dict[str, Any]]] = [
            (ts, r) for r in readings if (ts := self._reading_timestamp(r)) is not None
        ]
        if not timestamped:
            return None
        return max(timestamped, key=lambda pair: pair[0])[1]

    async def get_radar_frames(self, *, limit: int = 1) -> list[RadarFrameData]:
        stations = await self._fetch_stations()
        today = datetime.now(UTC).date()
        readings_by_station: dict[str, list[dict[str, Any]]] = {}
        for station in stations:
            code = _first(station, _CODE_KEYS)
            if code is None:
                continue
            try:
                readings_by_station[str(code)] = await self._fetch_station_readings(
                    str(code), today
                )
            except (httpx.HTTPError, WeatherProviderUnavailableError):
                continue

        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        frames: list[RadarFrameData] = []
        for i in range(limit):
            slot = now - timedelta(hours=limit - 1 - i)
            cells: list[RawCell] = []
            for station in stations:
                code = _first(station, _CODE_KEYS)
                lat = _as_float(station, _LAT_KEYS)
                lon = _as_float(station, _LON_KEYS)
                if code is None or lat is None or lon is None:
                    continue
                reading = next(
                    (
                        r
                        for r in readings_by_station.get(str(code), [])
                        if self._reading_timestamp(r) == slot
                    ),
                    None,
                )
                if reading is None:
                    continue
                rain_rate = _as_float(reading, _RAIN_KEYS)
                if rain_rate is None or rain_rate < self._min_rain_rate_mm_h:
                    continue
                dbz = round(marshall_palmer_dbz(rain_rate), 1)
                cells.append(
                    RawCell(
                        latitude=lat, longitude=lon, max_reflectivity=dbz, average_reflectivity=dbz
                    )
                )
            frames.append(
                RadarFrameData(provenance=self._provenance(), captured_at=slot, cells=cells)
            )
        return frames

    async def get_warnings(self, latitude: float, longitude: float) -> list[Warning]:
        stations = await self._fetch_stations()
        station = self._nearest_station(latitude, longitude, stations)
        uf = _first(station, _UF_KEYS)
        if uf is None:
            return []
        response = await self._client.get(f"{self._avisos_url}/avisos/ativos")
        if response.status_code != httpx.codes.OK:
            return []
        try:
            data = response.json()
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        warnings: list[Warning] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            estados = item.get("estados") or item.get("uf") or ""
            if str(uf).upper() not in str(estados).upper():
                continue
            issued_raw = item.get("data_inicio") or item.get("inicio")
            try:
                issued_at = (
                    datetime.fromisoformat(str(issued_raw)) if issued_raw else datetime.now(UTC)
                )
            except ValueError:
                issued_at = datetime.now(UTC)
            warnings.append(
                Warning(
                    provenance=self._provenance(kind=WeatherSourceKind.OFFICIAL_WARNING),
                    issued_at=issued_at,
                    kind=str(item.get("tipo") or item.get("aviso") or "aviso"),
                    severity=str(item.get("severidade") or item.get("nivel") or "unknown"),
                    description=str(item.get("descricao") or item.get("mensagem") or ""),
                )
            )
        return warnings

    async def _resolve_ibge_geocode(self, uf: str, station_name: str) -> str:
        response = await self._client.get(f"{self._ibge_localidades_url}/estados/{uf}/municipios")
        response.raise_for_status()
        municipios = response.json()
        if not isinstance(municipios, list):
            raise WeatherProviderUnavailableError("Unexpected IBGE municipios response shape.")
        target = _normalize_name(station_name)
        for item in municipios:
            if not isinstance(item, dict):
                continue
            nome = item.get("nome")
            geocode = item.get("id")
            if nome is None or geocode is None:
                continue
            if _normalize_name(str(nome)) == target:
                return str(geocode)
        raise WeatherProviderUnavailableError(
            f"No IBGE municipality named {station_name!r} found for UF {uf!r}."
        )

    async def _fetch_previsao(self, geocode: str) -> dict[str, Any]:
        response = await self._client.get(f"{self._previsao_url}/previsao/{geocode}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or geocode not in data:
            raise WeatherProviderUnavailableError(
                f"Unexpected INMET previsao response shape for geocode {geocode!r}."
            )
        days = data[geocode]
        if not isinstance(days, dict):
            raise WeatherProviderUnavailableError(
                f"Unexpected INMET previsao days shape for geocode {geocode!r}."
            )
        return days

    async def get_forecast(self, latitude: float, longitude: float) -> Forecast:
        stations = await self._fetch_stations()
        station = self._nearest_station(latitude, longitude, stations)
        uf = _first(station, _UF_KEYS)
        name = _first(station, _NAME_KEYS)
        code = _first(station, _CODE_KEYS)
        if uf is None or name is None:
            raise WeatherProviderUnavailableError(
                "Nearest INMET station is missing UF/name for geocode resolution."
            )
        geocode = await self._resolve_ibge_geocode(str(uf), str(name))
        days = await self._fetch_previsao(geocode)

        points: list[ForecastPoint] = []

        # Yesterday: a real measurement (not a forecast), for a bit of
        # before/after context — honest about what it is via its position.
        if code is not None:
            yesterday = datetime.now(UTC).date() - timedelta(days=1)
            try:
                readings = await self._fetch_station_readings(str(code), yesterday)
                latest_yesterday = self._latest_reading(readings)
            except (httpx.HTTPError, WeatherProviderUnavailableError):
                latest_yesterday = None
            if latest_yesterday is not None:
                ts = self._reading_timestamp(latest_yesterday) or datetime.combine(
                    yesterday, datetime.min.time(), tzinfo=UTC
                )
                points.append(
                    ForecastPoint(
                        time=ts,
                        temperature_c=_as_float(latest_yesterday, _TEMP_KEYS),
                        precipitation_probability=None,
                        precipitation_mm=_as_float(latest_yesterday, _RAIN_KEYS),
                    )
                )

        # Today onward: real forecast from INMET (capped at 5 days by the
        # API itself — confirmed live, not a limit we impose).
        for date_str, periods in days.items():
            try:
                day = datetime.strptime(date_str, "%d/%m/%Y").replace(tzinfo=UTC)
            except ValueError:
                continue
            period = (
                periods.get("tarde") or periods.get("manha") or periods.get("noite")
                if isinstance(periods, dict)
                else None
            )
            if not isinstance(period, dict):
                continue
            points.append(
                ForecastPoint(
                    time=day,
                    temperature_c=_as_float(period, ("temp_max",)),
                    # INMET gives a free-text summary ("Poucas nuvens"), not a
                    # numeric probability or mm — left unset rather than
                    # invented from text.
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

    async def aclose(self) -> None:
        await self._client.aclose()
