"""SentinelHubNdviProvider — real NDVI via Copernicus Data Space Ecosystem's
Sentinel Hub Statistical API (FASE 29, ADR-0053).

Endpoints and request/response shapes below were verified against the
official Copernicus documentation as of 2026-08-24
(https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html
and .../Overview/Authentication.html) — unlike this project's weather
providers, this one has **not** been exercised against a live account (no
Copernicus credentials available in this environment). `ndvi_enabled`
defaults to `false` for exactly this reason: verify against a real account
before flipping it on anywhere real usage depends on it.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings
from app.core.enums import WeatherSourceKind
from app.ndvi.provider import NdviObservation, NdviProvider, NdviProviderUnavailableError
from app.weather.provider import Provenance

_PROVIDER_NAME = "Copernicus Sentinel Hub"

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
                "resx": 10,
                "resy": 10,
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
            if sample_count == 0 or total == 0:
                continue
            return NdviObservation(
                provenance=Provenance(
                    source_name=_PROVIDER_NAME,
                    source_kind=WeatherSourceKind.SATELLITE,
                    is_mock=False,
                ),
                observed_at=datetime.fromisoformat(interval["interval"]["from"]),
                ndvi_mean=stats["mean"],
                valid_pixel_percent=round(sample_count / total * 100, 1),
            )

        raise NdviProviderUnavailableError(
            f"Nenhum pixel válido (sem nuvem) nos últimos {lookback_days:.0f} dias para este talhão"
        )
