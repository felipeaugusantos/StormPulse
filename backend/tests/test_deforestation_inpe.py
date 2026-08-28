"""Tests for InpeDeforestationProvider — request shape and the "a source
that fails must never look like a clean zero-alert check" contract (item
DETER). Uses `httpx.MockTransport`, same pattern as
`test_ndvi_sentinel_hub.py`, since the real endpoints are public
government WFS with no test double we could hit in CI.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.deforestation.inpe import InpeDeforestationProvider
from app.deforestation.provider import DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE

_TALHAO = {
    "type": "Polygon",
    "coordinates": [
        [
            [-55.66, -1.44],
            [-55.65, -1.44],
            [-55.65, -1.43],
            [-55.66, -1.43],
            [-55.66, -1.44],
        ]
    ],
}

_DETER_FEATURE = {
    "type": "Feature",
    "geometry": {"type": "MultiPolygon", "coordinates": []},
    "properties": {
        "classname": "DESMATAMENTO_CR",
        "view_date": "2026-07-01",
        "municipality": "obidos",
        "uf": "PA",
        "areamunkm": 0.5,
    },
}

_PRODES_FEATURE = {
    "type": "Feature",
    "geometry": {"type": "MultiPolygon", "coordinates": []},
    "properties": {
        "class_name": "DESMATAMENTO",
        "image_date": "2026-01-15",
        "year": 2026,
        "state": "GO",
        "area_km": 1.2,
    },
}


def _provider(handler: Any) -> InpeDeforestationProvider:
    return InpeDeforestationProvider(
        deter_amz_wfs_url="https://example.test/deter-amz/ows",
        prodes_cerrado_wfs_url="https://example.test/prodes-cerrado-nb/ows",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_check_sends_an_intersects_cql_filter_in_lon_lat_order() -> None:
    captured_filters: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cql = request.url.params.get("CQL_FILTER", "")
        if "deter-amz" in str(request.url):
            captured_filters.append(cql)
            return httpx.Response(200, json={"features": [_DETER_FEATURE]})
        return httpx.Response(200, json={"features": []})

    provider = _provider(handler)
    result = await provider.check(json.dumps(_TALHAO), lookback_years=3)

    assert result.checked_sources == [DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE]
    assert result.unavailable_sources == []
    assert captured_filters == [
        "INTERSECTS(geom,SRID=4326;POLYGON((-55.66 -1.44,-55.65 -1.44,"
        "-55.65 -1.43,-55.66 -1.43,-55.66 -1.44)))"
    ]


async def test_check_parses_alerts_from_both_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "deter-amz" in str(request.url):
            return httpx.Response(200, json={"features": [_DETER_FEATURE]})
        return httpx.Response(200, json={"features": [_PRODES_FEATURE]})

    provider = _provider(handler)
    result = await provider.check(json.dumps(_TALHAO), lookback_years=3)

    assert len(result.alerts) == 2
    deter_alert = next(a for a in result.alerts if a.source == DETER_AMZ_SOURCE)
    assert deter_alert.classname == "DESMATAMENTO_CR"
    assert deter_alert.municipio == "obidos"
    assert deter_alert.uf == "PA"
    assert deter_alert.area_ha == 50.0
    prodes_alert = next(a for a in result.alerts if a.source == PRODES_CERRADO_SOURCE)
    assert prodes_alert.classname == "DESMATAMENTO"
    assert prodes_alert.uf == "GO"
    assert prodes_alert.area_ha == 120.0


async def test_check_marks_a_source_unavailable_on_network_failure_without_raising() -> None:
    """The real DETER-AMZ WFS proved flaky in development (connection-pool
    errors, timeouts) — a failure on one source must never raise, and must
    never be indistinguishable from "checked, zero alerts" for that source."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "deter-amz" in str(request.url):
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json={"features": [_PRODES_FEATURE]})

    provider = _provider(handler)
    result = await provider.check(json.dumps(_TALHAO), lookback_years=3)

    assert result.unavailable_sources == [DETER_AMZ_SOURCE]
    assert result.checked_sources == [PRODES_CERRADO_SOURCE]
    assert len(result.alerts) == 1
    assert result.alerts[0].source == PRODES_CERRADO_SOURCE


async def test_check_marks_a_source_unavailable_on_http_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "prodes-cerrado" in str(request.url):
            return httpx.Response(500, text="internal error")
        return httpx.Response(200, json={"features": []})

    provider = _provider(handler)
    result = await provider.check(json.dumps(_TALHAO), lookback_years=3)

    assert result.unavailable_sources == [PRODES_CERRADO_SOURCE]
    assert result.checked_sources == [DETER_AMZ_SOURCE]


async def test_check_filters_out_alerts_older_than_the_lookback_window() -> None:
    old_feature = {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": []},
        "properties": {
            "classname": "DESMATAMENTO_CR",
            "view_date": "2015-01-01",
            "municipality": "obidos",
            "uf": "PA",
            "areamunkm": 0.5,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "deter-amz" in str(request.url):
            return httpx.Response(200, json={"features": [old_feature]})
        return httpx.Response(200, json={"features": []})

    provider = _provider(handler)
    result = await provider.check(json.dumps(_TALHAO), lookback_years=3)

    assert result.alerts == []
