"""InpeDeforestationProvider — real deforestation-alert lookup against
INPE/Terrabrasilis's own public WFS (item DETER).

Two independent, unauthenticated GeoServer WFS 2.0.0 endpoints, verified
live against their actual `DescribeFeatureType`/`GetFeature` responses
(2026-08-28) before writing this:

- DETER-AMZ (`deter-amz:deter_amz`) — near-real-time alerts, Amazônia Legal
  + Pantanal + non-forest Amazon. Confirmed fields: `classname`,
  `view_date` (ISO date string), `uf`, `municipality`, `areamunkm`
  (the alert polygon's area *within that municipality*, in km² — a slight
  approximation of the polygon's own total area for a polygon that doesn't
  itself straddle a municipal boundary, which is the common case).
- PRODES-Cerrado (`prodes-cerrado-nb:yearly_deforestation`) — annual
  clear-cut deforestation, Cerrado biome. Confirmed fields: `class_name`,
  `image_date`/`year`, `state`, `area_km` (the polygon's own area).

**Real instability found during development**: even a plain, unfiltered
`GetFeature` against DETER-AMZ intermittently failed with GeoServer's own
`"Unable to obtain connection: ... pool error"` (a backend DB connection
pool exhausted on INPE's side, not a client-side issue) and outright
timeouts past 20s on a single simple query. This is why each source is
tried independently with its own short timeout and a failure here is
*never* raised as an exception — a `DeforestationCheckResult` marking that
source `unavailable_sources` is a normal, expected outcome (see
`app.deforestation.provider`), not something callers need to catch.

Geometry filter uses `CQL_FILTER=INTERSECTS(geom, SRID=4326;POLYGON(...))`
— an EWKT literal, always given in (lon, lat) axis order by convention —
deliberately instead of the plain `bbox=` WFS parameter, whose axis order
for EPSG:4674/4326 depends on GeoServer's CITE-compliance configuration and
is easy to get backwards silently.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.deforestation.provider import (
    DETER_AMZ_SOURCE,
    PRODES_CERRADO_SOURCE,
    DeforestationAlert,
    DeforestationCheckResult,
    DeforestationProvider,
)

_PROVIDER_NAME = "INPE Terrabrasilis (DETER/PRODES)"


def _polygon_wkt(boundary_geojson: str) -> str:
    ring = json.loads(boundary_geojson)["coordinates"][0]
    points = ",".join(f"{lon} {lat}" for lon, lat in ring)
    return f"SRID=4326;POLYGON(({points}))"


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class InpeDeforestationProvider(DeforestationProvider):
    def __init__(
        self,
        *,
        deter_amz_wfs_url: str,
        prodes_cerrado_wfs_url: str,
        http_timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._deter_amz_wfs_url = deter_amz_wfs_url
        self._prodes_cerrado_wfs_url = prodes_cerrado_wfs_url
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=http_timeout_seconds)

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def _get_features(self, wfs_url: str, type_name: str, wkt: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            wfs_url,
            params={
                "service": "wfs",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeName": type_name,
                "outputFormat": "application/json",
                "CQL_FILTER": f"INTERSECTS(geom,{wkt})",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise httpx.HTTPError(f"Resposta inesperada do WFS {wfs_url}")
        return list(payload.get("features", []))

    async def _check_deter_amz(
        self, wkt: str, min_date: date
    ) -> tuple[bool, list[DeforestationAlert]]:
        try:
            features = await self._get_features(self._deter_amz_wfs_url, "deter-amz:deter_amz", wkt)
        except (httpx.HTTPError, ValueError):
            return False, []
        alerts = []
        for feature in features:
            props = feature.get("properties", {})
            detected_at = _parse_date(props.get("view_date"))
            if detected_at is not None and detected_at < min_date:
                continue
            area_km = props.get("areamunkm")
            alerts.append(
                DeforestationAlert(
                    source=DETER_AMZ_SOURCE,
                    classname=props.get("classname") or "DESCONHECIDO",
                    detected_at=detected_at,
                    area_ha=round(area_km * 100, 2) if area_km else None,
                    municipio=props.get("municipality"),
                    uf=props.get("uf"),
                )
            )
        return True, alerts

    async def _check_prodes_cerrado(
        self, wkt: str, min_date: date
    ) -> tuple[bool, list[DeforestationAlert]]:
        try:
            features = await self._get_features(
                self._prodes_cerrado_wfs_url,
                "prodes-cerrado-nb:yearly_deforestation",
                wkt,
            )
        except (httpx.HTTPError, ValueError):
            return False, []
        alerts = []
        for feature in features:
            props = feature.get("properties", {})
            detected_at = _parse_date(props.get("image_date"))
            if detected_at is None and props.get("year"):
                detected_at = date(int(props["year"]), 1, 1)
            if detected_at is not None and detected_at < min_date:
                continue
            area_km = props.get("area_km")
            alerts.append(
                DeforestationAlert(
                    source=PRODES_CERRADO_SOURCE,
                    classname=props.get("class_name") or "DESCONHECIDO",
                    detected_at=detected_at,
                    area_ha=round(area_km * 100, 2) if area_km else None,
                    municipio=None,
                    uf=props.get("state"),
                )
            )
        return True, alerts

    async def check(
        self, boundary_geojson: str, *, lookback_years: float
    ) -> DeforestationCheckResult:
        wkt = _polygon_wkt(boundary_geojson)
        min_date = (datetime.now(UTC) - timedelta(days=lookback_years * 365)).date()

        deter_ok, deter_alerts = await self._check_deter_amz(wkt, min_date)
        prodes_ok, prodes_alerts = await self._check_prodes_cerrado(wkt, min_date)

        checked_sources = []
        unavailable_sources = []
        if deter_ok:
            checked_sources.append(DETER_AMZ_SOURCE)
        else:
            unavailable_sources.append(DETER_AMZ_SOURCE)
        if prodes_ok:
            checked_sources.append(PRODES_CERRADO_SOURCE)
        else:
            unavailable_sources.append(PRODES_CERRADO_SOURCE)

        return DeforestationCheckResult(
            checked_sources=checked_sources,
            unavailable_sources=unavailable_sources,
            alerts=deter_alerts + prodes_alerts,
        )
