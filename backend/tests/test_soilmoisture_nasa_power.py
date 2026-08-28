"""Tests for NasaPowerSoilMoistureProvider — request shape and the
"walk backwards past fill values" contract (item NASA). Uses
`httpx.MockTransport`, same pattern as `test_ndvi_sentinel_hub.py`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.soilmoisture.nasa_power import NasaPowerSoilMoistureProvider
from app.soilmoisture.provider import SoilMoistureProviderUnavailableError


def _provider(handler: Any) -> NasaPowerSoilMoistureProvider:
    return NasaPowerSoilMoistureProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _response(values: dict[str, dict[str, float]]) -> httpx.Response:
    return httpx.Response(200, json={"properties": {"parameter": values}})


async def test_sends_the_three_soil_wetness_parameters_and_ag_community() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["parameters"] = request.url.params.get("parameters", "")
        captured["community"] = request.url.params.get("community", "")
        return _response(
            {
                "GWETTOP": {"20260827": 0.33},
                "GWETROOT": {"20260827": 0.46},
                "GWETPROF": {"20260827": 0.46},
            }
        )

    provider = _provider(handler)
    observation = await provider.get_soil_moisture(-21.18, -47.81)

    assert captured["parameters"] == "GWETTOP,GWETROOT,GWETPROF"
    assert captured["community"] == "AG"
    assert observation.surface_wetness_percent == 33.0
    assert observation.root_zone_wetness_percent == 46.0
    assert observation.profile_wetness_percent == 46.0
    assert observation.provenance.is_mock is False


async def test_walks_backwards_past_fill_values() -> None:
    """The most recent 1-2 days routinely come back as -999.0 (model still
    processing) — must fall back to the newest fully-populated day."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "GWETTOP": {"20260825": 0.30, "20260826": -999.0, "20260827": -999.0},
                "GWETROOT": {"20260825": 0.40, "20260826": -999.0, "20260827": -999.0},
                "GWETPROF": {"20260825": 0.42, "20260826": -999.0, "20260827": -999.0},
            }
        )

    provider = _provider(handler)
    observation = await provider.get_soil_moisture(-21.18, -47.81)

    assert observation.observed_at.isoformat() == "2026-08-25"
    assert observation.surface_wetness_percent == 30.0


async def test_partial_fill_across_parameters_still_skips_that_day() -> None:
    """A day must be skipped if *any* of the three parameters is a fill
    value, even if the others look valid — never mix a real value from one
    day with a placeholder from another."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "GWETTOP": {"20260826": 0.31, "20260827": 0.33},
                "GWETROOT": {"20260826": 0.45, "20260827": -999.0},
                "GWETPROF": {"20260826": 0.44, "20260827": 0.46},
            }
        )

    provider = _provider(handler)
    observation = await provider.get_soil_moisture(-21.18, -47.81)

    assert observation.observed_at.isoformat() == "2026-08-26"


async def test_raises_when_every_day_is_a_fill_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "GWETTOP": {"20260827": -999.0},
                "GWETROOT": {"20260827": -999.0},
                "GWETPROF": {"20260827": -999.0},
            }
        )

    provider = _provider(handler)
    with pytest.raises(SoilMoistureProviderUnavailableError):
        await provider.get_soil_moisture(-21.18, -47.81)


async def test_raises_on_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = _provider(handler)
    with pytest.raises(SoilMoistureProviderUnavailableError):
        await provider.get_soil_moisture(-21.18, -47.81)


async def test_raises_on_unexpected_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = _provider(handler)
    with pytest.raises(SoilMoistureProviderUnavailableError):
        await provider.get_soil_moisture(-21.18, -47.81)
