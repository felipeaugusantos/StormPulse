"""SentinelHubNdviProvider — real NDVI via Copernicus Data Space Ecosystem's
Sentinel Hub Statistical API (FASE 29, ADR-0053).

Endpoints and request/response shapes below were verified against the
official Copernicus documentation as of 2026-08-24
(https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html
and .../Overview/Authentication.html), and — since ADR-0053's follow-up —
against a real account with real talhões (see the ADR's "bug real
encontrado" section).

**Real bug found and fixed on first live run**: the request originally sent
`resx`/`resy: 10` alongside `bounds.properties.crs` set to EPSG:4326
(degrees). Sentinel Hub interprets `resx`/`resy` in the *bounds CRS's own
units* — so "10" meant 10 **degrees** per pixel (over 1000km), not 10
meters, collapsing every talhão (however small) into a single giant pixel
(`geometryPixelCount: 1` in the response) whose mean mixed in far more than
just the field itself. Fixed by requesting `width`/`height` in pixels
instead, computed from the polygon's own bounding box in meters (via
`engine.geo.haversine_km`, already used elsewhere in this project) divided
by the target ~10m resolution — CRS stays EPSG:4326 throughout, no
reprojection library needed.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import Settings
from app.core.enums import WeatherSourceKind
from app.ndvi.provider import NdviObservation, NdviProvider, NdviProviderUnavailableError
from app.weather.provider import Provenance
from engine.geo import haversine_km

_PROVIDER_NAME = "Copernicus Sentinel Hub"

_TARGET_RESOLUTION_M = 10.0
# Sentinel Hub cap for a single Process/Statistical request's raster size —
# comfortably above any real talhão (a 2500x2500 10m grid is 625 km²).
_MAX_PIXELS_PER_AXIS = 2500

# Single-band NDVI evalscript (Sentinel-2 L2A red/NIR) — the exact example
# from Copernicus's own Statistical API docs, output id "data" holds the
# NDVI value itself; "dataMask" marks cloud/nodata pixels as invalid so
# they're excluded from the mean.
_NDVI_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "data", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  }
}
function evaluatePixel(samples) {
  let ndvi = (samples.B08 - samples.B04) / (samples.B08 + samples.B04)
  let validNDVIMask = 1
  if (samples.B08 + samples.B04 == 0) { validNDVIMask = 0 }
  return { data: [ndvi], dataMask: [samples.dataMask * validNDVIMask] }
}"""


# Colored NDVI visualization (Process API, not the Statistical API above)
# — item "imagem do talhão" in the weekly report. Cloud/shadow/snow pixels
# (SCL classes 3, 8, 9, 10, 11 — cloud shadow, medium/high-probability
# cloud, thin cirrus, snow/ice) are excluded via alpha instead of being
# colored as if they were real vegetation data; a simple 3-stop ramp
# (red-brown for low/negative NDVI, through yellow, to green for high)
# communicates "healthier here, stressed there" at a glance — it isn't
# meant to be a scientifically calibrated colormap.
_NDVI_IMAGE_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: { bands: 4 }
  }
}
function evaluatePixel(samples) {
  let scl = samples.SCL
  let isCloudOrSnow = scl == 3 || scl == 8 || scl == 9 || scl == 10 || scl == 11
  let denom = samples.B08 + samples.B04
  if (samples.dataMask == 0 || isCloudOrSnow || denom == 0) {
    return [0, 0, 0, 0]
  }
  let ndvi = (samples.B08 - samples.B04) / denom
  let r, g, b
  if (ndvi < 0.2) {
    let t = Math.max(0, (ndvi + 0.2) / 0.4)
    r = 0.65
    g = 0.3 + t * 0.3
    b = 0.1
  } else {
    let t = Math.min(1, (ndvi - 0.2) / 0.6)
    r = 0.85 - t * 0.75
    g = 0.6 + t * 0.3
    b = 0.1
  }
  return [r, g, b, 1]
}"""


def _pixel_dimensions(polygon: dict[str, Any]) -> tuple[int, int]:
    """Bbox width/height in ~10m pixels, computed from real-world extent.

    Sentinel Hub interprets `resx`/`resy` in the bounds CRS's own units — for
    EPSG:4326 that's degrees, not meters — so requesting a resolution
    directly silently produced a single giant pixel per talhão. Asking for
    `width`/`height` in pixels instead sidesteps that entirely.
    """
    ring = polygon["coordinates"][0]
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    lat_mid = (lat_min + lat_max) / 2

    width_m = haversine_km(lat_mid, lon_min, lat_mid, lon_max) * 1000
    height_m = haversine_km(lat_min, lon_min, lat_max, lon_min) * 1000

    width_px = min(_MAX_PIXELS_PER_AXIS, max(1, round(width_m / _TARGET_RESOLUTION_M)))
    height_px = min(_MAX_PIXELS_PER_AXIS, max(1, round(height_m / _TARGET_RESOLUTION_M)))
    return width_px, height_px


class SentinelHubNdviProvider(NdviProvider):
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        if not settings.ndvi_sh_client_id or not settings.ndvi_sh_client_secret:
            raise NdviProviderUnavailableError(
                "NDVI_SH_CLIENT_ID/NDVI_SH_CLIENT_SECRET não configurados"
            )
        self._settings = settings
        # Narrowed once here, not re-read from `self._settings` later — mypy
        # can't see across methods that the check above already guarantees
        # these aren't None.
        self._client_id = settings.ndvi_sh_client_id
        self._client_secret = settings.ndvi_sh_client_secret.get_secret_value()
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(timeout=settings.ndvi_http_timeout_seconds)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def _access_token(self) -> str:
        # Reused across calls within its validity window — Copernicus rate
        # limits the token endpoint itself; a fresh token per NDVI request
        # would be both wasteful and eventually throttled.
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        try:
            resp = await self._client.post(
                self._settings.ndvi_sh_token_url,
                headers={"content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise NdviProviderUnavailableError(
                "Falha ao autenticar no Copernicus Sentinel Hub"
            ) from exc
        self._token = payload["access_token"]
        # A comfortable margin under the real expiry (usually ~1h) so a
        # request never starts with a token that expires mid-flight.
        self._token_expires_at = time.monotonic() + max(payload.get("expires_in", 300) - 60, 30)
        return self._token

    async def get_ndvi(self, boundary_geojson: str, *, lookback_days: float) -> NdviObservation:
        polygon = json.loads(boundary_geojson)
        now = datetime.now(UTC)
        start = now - timedelta(days=lookback_days)
        token = await self._access_token()
        width_px, height_px = _pixel_dimensions(polygon)

        request_body = {
            "input": {
                "bounds": {
                    "geometry": polygon,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {"type": "sentinel-2-l2a", "dataFilter": {"mosaickingOrder": "leastRecent"}}
                ],
            },
            "aggregation": {
                "timeRange": {"from": start.isoformat(), "to": now.isoformat()},
                "aggregationInterval": {"of": "P1D"},
                "evalscript": _NDVI_EVALSCRIPT,
                "width": width_px,
                "height": height_px,
            },
            "calculations": {"default": {"statistics": {"default": {}}}},
        }

        try:
            resp = await self._client.post(
                self._settings.ndvi_sh_statistics_url,
                headers={"Authorization": f"Bearer {token}"},
                json=request_body,
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise NdviProviderUnavailableError(
                "Falha ao consultar o Sentinel Hub Statistical API"
            ) from exc

        # Most recent interval that actually has usable (non-cloud) pixels —
        # `data` is chronological, walk it backwards.
        for interval in reversed(payload.get("data", [])):
            try:
                stats = interval["outputs"]["data"]["bands"]["B0"]["stats"]
            except KeyError:
                continue
            sample_count = stats.get("sampleCount", 0)
            no_data_count = stats.get("noDataCount", 0)
            total = sample_count + no_data_count
            mean = stats.get("mean")
            # Sentinel Hub can report a non-zero sampleCount yet still
            # give a degenerate `mean` for that interval — confirmed live
            # in production 2026-08-28: a talhão with 50% valid pixels got
            # `NaN` back (Python's `json` module parses the `NaN` token by
            # default). `ndvi_readings.ndvi_mean` really is NOT NULL at
            # the DB level (confirmed via `\d ndvi_readings`) — NaN isn't
            # SQL NULL, so it was never rejected there, but it *is*
            # unrepresentable in JSON, so Pydantic's response serializer
            # silently turned it into `null` for the API response,
            # producing a reading that looked fine end-to-end until the
            # frontend tried to format it. Treated the same as "no usable
            # pixels" here: fall back to the next older interval instead
            # of ever persisting a mean nothing downstream can use.
            if sample_count == 0 or total == 0 or mean is None or math.isnan(mean):
                continue
            return NdviObservation(
                provenance=Provenance(
                    source_name=_PROVIDER_NAME,
                    source_kind=WeatherSourceKind.SATELLITE,
                    is_mock=False,
                ),
                observed_at=datetime.fromisoformat(interval["interval"]["from"]),
                ndvi_mean=mean,
                valid_pixel_percent=round(sample_count / total * 100, 1),
            )

        raise NdviProviderUnavailableError(
            f"Nenhum pixel válido (sem nuvem) nos últimos {lookback_days:.0f} dias para este talhão"
        )

    async def get_ndvi_image(self, boundary_geojson: str, *, lookback_days: float) -> bytes:
        polygon = json.loads(boundary_geojson)
        now = datetime.now(UTC)
        start = now - timedelta(days=lookback_days)
        token = await self._access_token()
        width_px, height_px = _pixel_dimensions(polygon)

        request_body = {
            "input": {
                "bounds": {
                    "geometry": polygon,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "mosaickingOrder": "leastRecent",
                            "timeRange": {"from": start.isoformat(), "to": now.isoformat()},
                        },
                    }
                ],
            },
            "output": {
                "width": width_px,
                "height": height_px,
                "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
            },
            "evalscript": _NDVI_IMAGE_EVALSCRIPT,
        }

        try:
            resp = await self._client.post(
                self._settings.ndvi_sh_process_url,
                headers={"Authorization": f"Bearer {token}"},
                json=request_body,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise NdviProviderUnavailableError(
                "Falha ao consultar o Sentinel Hub Process API"
            ) from exc
        return resp.content
