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

from app.core.config import Settings
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
