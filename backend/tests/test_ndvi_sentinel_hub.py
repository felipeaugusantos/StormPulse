"""Tests for SentinelHubNdviProvider's request-building — specifically the
width/height pixel-sizing fix (a real production bug: `resx`/`resy: 10` was
interpreted as 10 *degrees*, since the bounds CRS is EPSG:4326, collapsing
every talhão into a single pixel; see ADR-0053).

`test_ndvi_pipeline.py` only ever injects a fake provider, so it never
exercised this request-building code — exactly why the bug shipped
undetected. These tests use `httpx.MockTransport` (same pattern as
`test_weather_open_meteo.py`) to inspect the real outgoing request body.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.ndvi.provider import NdviProviderUnavailableError
from app.ndvi.sentinel_hub import SentinelHubNdviProvider, _pixel_dimensions

# A small real-shaped talhão (~330m x ~220m), matching the scale of the
# production polygons that surfaced the original bug.
_SMALL_TALHAO = {
    "type": "Polygon",
    "coordinates": [
        [
            [-47.79248, -21.19508],
            [-47.78900, -21.19508],
            [-47.78900, -21.19308],
            [-47.79248, -21.19308],
            [-47.79248, -21.19508],
        ]
    ],
}

_STATS_RESPONSE = {
    "data": [
        {
            "interval": {"from": "2026-08-20T00:00:00Z", "to": "2026-08-21T00:00:00Z"},
            "outputs": {
                "data": {
                    "bands": {
                        "B0": {
                            "stats": {
                                "mean": 0.62,
                                "sampleCount": 900,
                                "noDataCount": 100,
                            }
                        }
                    }
                }
            },
        }
    ]
}


def _settings() -> Settings:
    return Settings(
        environment="test",
        ndvi_enabled=True,
        ndvi_sh_client_id="fake",
        ndvi_sh_client_secret="fake",
    )


def test_pixel_dimensions_are_many_pixels_not_one() -> None:
    """The original bug produced geometryPixelCount == 1 for every real
    talhão; the fix must request a raster with real width/height instead."""
    width_px, height_px = _pixel_dimensions(_SMALL_TALHAO)

    assert width_px > 1
    assert height_px > 1
    # ~330m / 10m and ~220m / 10m — roughly, not exactly (haversine vs flat).
    assert 25 <= width_px <= 40
    assert 18 <= height_px <= 28


def test_pixel_dimensions_capped_for_a_huge_polygon() -> None:
    huge = {
        "type": "Polygon",
        "coordinates": [
            [
                [-50.0, -22.0],
                [-40.0, -22.0],
                [-40.0, -15.0],
                [-50.0, -15.0],
                [-50.0, -22.0],
            ]
        ],
    }
    width_px, height_px = _pixel_dimensions(huge)
    assert width_px == 2500
    assert height_px == 2500


async def test_get_ndvi_sends_width_height_not_resx_resy() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_STATS_RESPONSE)

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    observation = await provider.get_ndvi(json.dumps(_SMALL_TALHAO), lookback_days=15)

    aggregation = captured["body"]["aggregation"]
    assert "resx" not in aggregation
    assert "resy" not in aggregation
    assert aggregation["width"] > 1
    assert aggregation["height"] > 1
    assert observation.ndvi_mean == 0.62
    assert observation.valid_pixel_percent == 90.0


async def test_get_ndvi_skips_an_interval_with_a_nan_mean_despite_valid_pixels() -> None:
    """Real production bug (2026-08-28): Sentinel Hub returned a non-zero
    sampleCount alongside `mean: NaN` for the most recent interval — a
    degenerate statistical result, not a real reading. `NaN` isn't SQL
    NULL (the DB column really is NOT NULL and never rejected it) but
    it's unrepresentable in JSON, so it silently became `null` in the API
    response — the reading looked fine end-to-end until the frontend
    tried to format it. Must fall back to the next older interval with a
    usable mean, same as it already does for zero-sample intervals."""
    body = (
        '{"data": [\n'
        '  {"interval": {"from": "2026-08-20T00:00:00Z", "to": "2026-08-21T00:00:00Z"},\n'
        '   "outputs": {"data": {"bands": {"B0": {"stats": '
        '{"mean": 0.55, "sampleCount": 800, "noDataCount": 200}}}}}},\n'
        '  {"interval": {"from": "2026-08-25T00:00:00Z", "to": "2026-08-26T00:00:00Z"},\n'
        '   "outputs": {"data": {"bands": {"B0": {"stats": '
        '{"mean": NaN, "sampleCount": 500, "noDataCount": 500}}}}}}\n'
        "]}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(
            200, content=body.encode("utf-8"), headers={"content-type": "application/json"}
        )

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    observation = await provider.get_ndvi(json.dumps(_SMALL_TALHAO), lookback_days=15)

    # The NaN-mean interval (2026-08-25, walked first since data is
    # chronological and the loop goes backwards) must be skipped in favor
    # of the older, usable one (2026-08-20) — never returned as-is.
    assert observation.ndvi_mean == 0.55
    assert observation.observed_at.isoformat() == "2026-08-20T00:00:00+00:00"


async def test_get_ndvi_skips_an_interval_with_a_null_mean_despite_valid_pixels() -> None:
    """A defensive case distinct from the NaN one above: `mean` missing/
    explicitly `null` in the payload, which `.get("mean")` would return
    as Python `None` rather than `float('nan')` — must be skipped the
    same way, not passed straight into `NdviObservation` where a `None`
    would fail the schema's `ndvi_mean: float` validation outright."""
    stats_response = {
        "data": [
            {
                "interval": {"from": "2026-08-20T00:00:00Z", "to": "2026-08-21T00:00:00Z"},
                "outputs": {
                    "data": {
                        "bands": {
                            "B0": {"stats": {"mean": 0.55, "sampleCount": 800, "noDataCount": 200}}
                        }
                    }
                },
            },
            {
                "interval": {"from": "2026-08-25T00:00:00Z", "to": "2026-08-26T00:00:00Z"},
                "outputs": {
                    "data": {
                        "bands": {
                            "B0": {"stats": {"mean": None, "sampleCount": 500, "noDataCount": 500}}
                        }
                    }
                },
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(200, json=stats_response)

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    observation = await provider.get_ndvi(json.dumps(_SMALL_TALHAO), lookback_days=15)

    # The null-mean interval (2026-08-25, walked first since data is
    # chronological and the loop goes backwards) must be skipped in favor
    # of the older, usable one (2026-08-20) — never returned as-is.
    assert observation.ndvi_mean == 0.55
    assert observation.observed_at.isoformat() == "2026-08-20T00:00:00+00:00"


async def test_get_ndvi_raises_when_every_interval_has_a_null_mean() -> None:
    stats_response = {
        "data": [
            {
                "interval": {"from": "2026-08-20T00:00:00Z", "to": "2026-08-21T00:00:00Z"},
                "outputs": {
                    "data": {
                        "bands": {
                            "B0": {"stats": {"mean": None, "sampleCount": 500, "noDataCount": 500}}
                        }
                    }
                },
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(200, json=stats_response)

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(NdviProviderUnavailableError):
        await provider.get_ndvi(json.dumps(_SMALL_TALHAO), lookback_days=15)


async def test_get_ndvi_image_sends_a_process_api_request_and_returns_the_raw_bytes() -> None:
    """Item "imagem do talhão" — a separate Sentinel Hub API (Process, not
    Statistical) that renders and returns the image directly; the request
    shape (single `responses` entry) means Sentinel Hub replies with raw
    bytes, not JSON wrapping them."""
    captured: dict[str, Any] = {}
    fake_png = b"\x89PNG\r\n\x1a\nfake-image-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=fake_png, headers={"content-type": "image/png"})

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    result = await provider.get_ndvi_image(json.dumps(_SMALL_TALHAO), lookback_days=15)

    assert result == fake_png
    assert captured["url"] == _settings().ndvi_sh_process_url
    assert captured["body"]["output"]["responses"] == [
        {"identifier": "default", "format": {"type": "image/png"}}
    ]
    assert "evalscript" in captured["body"]


async def test_get_ndvi_image_raises_on_a_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        raise httpx.ReadError("connection reset")

    provider = SentinelHubNdviProvider(
        _settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(NdviProviderUnavailableError):
        await provider.get_ndvi_image(json.dumps(_SMALL_TALHAO), lookback_days=15)
