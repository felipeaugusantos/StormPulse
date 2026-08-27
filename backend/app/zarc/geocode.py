"""IBGE município geocode resolution from lat/lon — item ZARC, ADR-0069.

Reuses the exact technique already established in
``app.weather.inmet.InmetWeatherProvider`` (nearest INMET automatic
station → station's own UF/name → exact-match against IBGE's public
municipality list for that UF) rather than inventing a second geocoding
path — no third-party geocoder involved, same honesty rule already
documented there.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from app.weather.inmet import (
    _LAT_KEYS,
    _LON_KEYS,
    _NAME_KEYS,
    _UF_KEYS,
    _as_float,
    _first,
    _normalize_name,
)
from engine.geo import haversine_km


class MunicipioNotResolvedError(Exception):
    """No IBGE município could be matched for this point."""


async def resolve_municipio_geocode(
    latitude: float,
    longitude: float,
    *,
    inmet_base_url: str,
    ibge_localidades_url: str,
    http_timeout_seconds: float = 10.0,
    max_station_distance_km: float = 100.0,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Returns the IBGE geocode (as a string) of the município nearest to
    ``latitude``/``longitude`` — raises ``MunicipioNotResolvedError`` when
    no INMET station is close enough or no matching município name is
    found, never a guessed/approximated code."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=http_timeout_seconds)
    try:
        try:
            response = await client.get(f"{inmet_base_url.rstrip('/')}/estacoes/T")
            response.raise_for_status()
            stations = response.json()
        except httpx.HTTPError as exc:
            raise MunicipioNotResolvedError(f"INMET station list request failed: {exc}") from exc
        if not isinstance(stations, list):
            raise MunicipioNotResolvedError("Unexpected INMET station list response shape.")

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
        if best is None or best_distance > max_station_distance_km:
            raise MunicipioNotResolvedError(
                f"No INMET station within {max_station_distance_km} km of "
                f"({latitude}, {longitude})."
            )

        uf = _first(best, _UF_KEYS)
        name = _first(best, _NAME_KEYS)
        if uf is None or name is None:
            raise MunicipioNotResolvedError("Nearest INMET station is missing UF/name.")

        try:
            municipios_response = await client.get(
                f"{ibge_localidades_url.rstrip('/')}/estados/{uf}/municipios"
            )
            municipios_response.raise_for_status()
            municipios = municipios_response.json()
        except httpx.HTTPError as exc:
            raise MunicipioNotResolvedError(f"IBGE municipios request failed: {exc}") from exc
        if not isinstance(municipios, list):
            raise MunicipioNotResolvedError("Unexpected IBGE municipios response shape.")

        target = _normalize_name(str(name))
        for item in municipios:
            if not isinstance(item, dict):
                continue
            nome = item.get("nome")
            geocode = item.get("id")
            if nome is None or geocode is None:
                continue
            if _normalize_name(str(nome)) == target:
                return str(geocode)

        raise MunicipioNotResolvedError(f"No IBGE municipality named {name!r} found for UF {uf!r}.")
    finally:
        if own_client:
            await client.aclose()
