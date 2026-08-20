"""Unit tests for the satellite pipeline's non-GDAL logic (FASE 16).

STAC querying, item selection and the pure velocity/dedup helpers are
covered here with no real network/GDAL involved (``httpx.MockTransport``,
same pattern as ``test_weather_inmet.py``). The GDAL-dependent detection
step (``_detect_systems``) and the DB-touching matching/alert logic are
verified separately: the former manually against real data (see
ADR-0009 — not practical in CI), the latter in
``test_integration_satellite.py`` (needs real Postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import Settings
from app.core.enums import AlertEventType
from app.satellite.models import ConvectiveWatch
from workers.satellite_pipeline import (
    DetectedSystem,
    SatelliteUnavailableError,
    _asset_href,
    _dedup_key,
    _item_timestamp,
    _stac_search,
    _velocity,
)

_ITEMS = [
    {
        "id": "GOES19_L2_ABI_202608192220",
        "properties": {"datetime": "2026-08-19T22:20:00Z"},
        "assets": {"B13": {"href": "https://example.test/ch13/old.nc"}},
    },
    {
        "id": "GOES19_L2_ABI_202608192230",
        "properties": {"datetime": "2026-08-19T22:30:00Z"},
        "assets": {"B13": {"href": "https://example.test/ch13/new.nc"}},
    },
]


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/search":
        return httpx.Response(200, json={"type": "FeatureCollection", "features": _ITEMS})
    return httpx.Response(404, json={"detail": "not found"})


@pytest.fixture
def settings() -> Settings:
    return Settings(
        satellite_enabled=True,
        satellite_stac_url="http://test",
        satellite_collection="GOES19-L2-CMI-1",
    )


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler), base_url="http://test")


def test_stac_search_sorts_newest_first(settings: Settings, client: httpx.Client) -> None:
    items = _stac_search(client, settings, limit=1)
    assert len(items) == 1
    assert items[0]["id"] == "GOES19_L2_ABI_202608192230"


def test_stac_search_respects_limit(settings: Settings, client: httpx.Client) -> None:
    items = _stac_search(client, settings, limit=2)
    assert len(items) == 2


def test_asset_href_returns_url_for_configured_band() -> None:
    href = _asset_href(_ITEMS[1], "B13")
    assert href == "https://example.test/ch13/new.nc"


def test_asset_href_raises_when_band_missing() -> None:
    with pytest.raises(SatelliteUnavailableError):
        _asset_href(_ITEMS[1], "B99")


def test_item_timestamp_parses_iso_with_z_suffix() -> None:
    ts = _item_timestamp(_ITEMS[1])
    assert ts == datetime(2026, 8, 19, 22, 30, tzinfo=UTC)


def test_dedup_key_is_stable_and_scoped_to_event() -> None:
    a = _dedup_key(AlertEventType.SATELLITE_WATCH_DETECTED, "loc-1", "watch-1")
    b = _dedup_key(AlertEventType.SATELLITE_WATCH_DISSIPATED, "loc-1", "watch-1")
    assert a != b
    assert a == _dedup_key(AlertEventType.SATELLITE_WATCH_DETECTED, "loc-1", "watch-1")


def test_velocity_is_none_for_the_first_observation() -> None:
    watch = ConvectiveWatch(
        first_detected_at=datetime.now(UTC),
        detected_at=datetime.now(UTC),
        latitude=-23.5,
        longitude=-46.6,
        min_brightness_temp_k=220.0,
        is_active=True,
        is_mock=False,
        experimental=True,
    )
    system = DetectedSystem(
        latitude=-23.5,
        longitude=-46.6,
        geometry_wkt="POINT(-46.6 -23.5)",
        min_brightness_temp_k=220.0,
        area_km2=4000.0,
    )
    # Same timestamp as "now" -> zero elapsed time -> no velocity computed.
    speed, direction = _velocity(watch, system, watch.detected_at)
    assert speed is None
    assert direction is None


def test_velocity_computed_from_previous_position() -> None:
    t0 = datetime(2026, 8, 19, 22, 0, tzinfo=UTC)
    t1 = datetime(2026, 8, 19, 22, 30, tzinfo=UTC)  # 30 minutes later
    watch = ConvectiveWatch(
        first_detected_at=t0,
        detected_at=t0,
        latitude=-23.5,
        longitude=-46.6,
        min_brightness_temp_k=220.0,
        is_active=True,
        is_mock=False,
        experimental=True,
    )
    # ~0.3 degrees north — a real displacement over 30 minutes.
    system = DetectedSystem(
        latitude=-23.2,
        longitude=-46.6,
        geometry_wkt="POINT(-46.6 -23.2)",
        min_brightness_temp_k=215.0,
        area_km2=4500.0,
    )
    speed, direction = _velocity(watch, system, t1)
    assert speed is not None and speed > 0
    assert direction is not None and 0 <= direction < 360
