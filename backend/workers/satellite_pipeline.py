"""Satellite convective-watch detection pipeline (FASE 16 — GOES-19 + TATHU).

Downloads the latest full-disk band-13 (10.3µm clean IR window) image from
INPE's public STAC catalog, detects cold/growing cloud tops (a precursor
signal — see ``app/satellite/models.py``), matches them against currently
active ``ConvectiveWatch`` rows by nearest centroid (our own simple
association, same spirit as ``engine/tracking/tracker.py`` — not TATHU's own
``trackers``/``forecasters`` modules, whose exact API we haven't exercised
against a real file), and emits alerts on detection/dissipation.

Off by default (``settings.satellite_enabled=False``) — real infra cost.

GDAL/TATHU imports are deliberately local to ``_detect_systems`` (not at
module level) so this module — and the STAC/persistence/alert-decision logic
below, which *is* unit-tested — stays importable in environments without
GDAL installed (e.g. a plain dev venv). The real runtime (the Docker image)
installs GDAL; see ``backend/Dockerfile``. numpy/Pillow (used only by
``_render_ir_image``, FASE 18) are local imports for the same reason — they
come from the ``satellite`` extra, not the base dependencies.
"""

from __future__ import annotations

import io
import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import AlertEventType, NotificationChannel, NotificationStatus, RiskLevel
from app.locations.models import Location
from app.notifications.models import Notification
from app.satellite.models import ConvectiveWatch, SatelliteImage
from engine.geo import haversine_km

logger = logging.getLogger(__name__)

# A satellite-derived watch is a lower-confidence, earlier-stage signal than
# a confirmed storm cell (radar/rain-rate) — always YELLOW, never computed
# from temperature into a fake 0-100 score. See ADR-0009.
_WATCH_LEVEL = RiskLevel.YELLOW

# Max distance to consider a freshly-detected system "the same" as a
# currently active DB watch, for continuity across cycles.
_MATCH_DISTANCE_KM = 100.0

# Grayscale-inverted IR convention (cold cloud top = bright, warm surface =
# dark) — the standard way infrared satellite imagery is displayed
# worldwide, not an invented color scheme. Values outside this range clip.
_IMAGE_TEMP_WARM_K = 320.0
_IMAGE_TEMP_COLD_K = 190.0
# The rendered frame is a *display* image, not the scientific grid — capped
# so a live web overlay stays light regardless of the configured resolution.
_IMAGE_MAX_DIMENSION = 800


class SatelliteUnavailableError(RuntimeError):
    """Raised when a satellite detection cycle can't honestly produce results."""


@dataclass
class SatelliteCycleSummary:
    enabled: bool
    frames_downloaded: int = 0
    systems_detected: int = 0
    watches_active: int = 0
    watches_dissipated: int = 0
    alerts: int = 0


@dataclass
class DetectedSystem:
    """Plain, TATHU-independent representation of one detected system."""

    latitude: float
    longitude: float
    geometry_wkt: str
    min_brightness_temp_k: float
    area_km2: float


@dataclass
class _CycleArtifacts:
    """What one detection cycle produces: the detections plus a display frame."""

    systems: list[DetectedSystem]
    image_png: bytes
    image_width: int
    image_height: int


def _render_ir_image(temps_k: Any, nodata: float | None) -> tuple[bytes, int, int]:
    """Grayscale-inverted IR PNG (RGBA) from a 2D array of Kelvin values.

    Pure function — no GDAL/TATHU involved, only numpy/Pillow (already real
    dependencies of the ``satellite`` extra via scikit-image) — so it's
    unit-testable with a synthetic array. ``temps_k`` is typed ``Any``
    instead of ``numpy.ndarray`` so this module still imports fine without
    numpy installed (plain ``dev`` venv); numpy/Pillow are imported locally
    here, same reasoning as the GDAL/TATHU imports in ``_detect_systems``.
    """
    import numpy as np
    from PIL import Image

    array = np.asarray(temps_k, dtype=np.float32)
    valid = np.ones(array.shape, dtype=bool) if nodata is None else ~np.isclose(array, nodata)

    span = _IMAGE_TEMP_WARM_K - _IMAGE_TEMP_COLD_K
    normalized = np.clip((_IMAGE_TEMP_WARM_K - array) / span, 0.0, 1.0)
    gray = (normalized * 255).astype(np.uint8)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    rgba = np.dstack([gray, gray, gray, alpha])

    image = Image.fromarray(rgba, mode="RGBA")
    longest_side = max(image.width, image.height)
    if longest_side > _IMAGE_MAX_DIMENSION:
        scale = _IMAGE_MAX_DIMENSION / longest_side
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), image.width, image.height


def _stac_search(client: httpx.Client, settings: Settings, *, limit: int) -> list[dict[str, Any]]:
    lon_min, lat_min, lon_max, lat_max = settings.satellite_extent_bbox
    # No `sortby` param: the search API rejects it (400) in the shape we
    # tried, and isn't needed — we sort client-side below instead of
    # trusting unspecified server ordering.
    response = client.get(
        f"{settings.satellite_stac_url.rstrip('/')}/search",
        params={
            "collections": settings.satellite_collection,
            "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
            "limit": max(limit, 5),
        },
    )
    response.raise_for_status()
    data = response.json()
    features = data.get("features")
    if not isinstance(features, list):
        raise SatelliteUnavailableError("Unexpected STAC search response shape.")
    features.sort(
        key=lambda item: str((item.get("properties") or {}).get("datetime", "")), reverse=True
    )
    return features[:limit]


def _asset_href(item: dict[str, Any], band: str) -> str:
    assets = item.get("assets")
    if not isinstance(assets, dict) or band not in assets:
        raise SatelliteUnavailableError(f"STAC item {item.get('id')!r} has no asset {band!r}.")
    href = assets[band].get("href")
    if not isinstance(href, str):
        raise SatelliteUnavailableError(f"STAC item {item.get('id')!r} asset {band!r} has no href.")
    return href


def _item_timestamp(item: dict[str, Any]) -> datetime:
    raw = (item.get("properties") or {}).get("datetime")
    if not raw:
        raise SatelliteUnavailableError(f"STAC item {item.get('id')!r} has no datetime.")
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _download(client: httpx.Client, href: str, dest_dir: Path) -> Path:
    dest = dest_dir / href.rsplit("/", 1)[-1]
    with client.stream("GET", href) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return dest


def _detect_systems(path: Path, settings: Settings, timestamp: datetime) -> _CycleArtifacts:
    """Reproject the raw satellite file, detect cold/growing cloud tops, and
    render a display PNG from the same reprojected grid (no 2nd download or
    reprojection pass just for the image).

    Real TATHU API, verified against the library's source (not guessed):
    ``ConvectiveSystem.getCentroid()`` -> ``(lon, lat)``,
    ``.getGeomWKT()`` -> WKT polygon, ``.attrs`` populated by
    ``StatisticalDescriptor`` with ``{'min', 'mean', 'count', ...}`` (Kelvin
    for min/mean; ``count`` = pixel count at the grid's resolution, used
    here for an honest area estimate — not fabricated). ``grid.ReadAsArray()``
    / ``GetNoDataValue()`` are plain GDAL Dataset APIs, verified the same way.
    """
    from osgeo import gdal
    from tathu.constants import LAT_LON_WGS84
    from tathu.satellite import goes_r
    from tathu.tracking import descriptors, detectors
    from tathu.tracking.utils import area2degrees

    grid = goes_r.sat2grid(
        str(path),
        list(settings.satellite_extent_bbox),
        settings.satellite_grid_resolution_km,
        LAT_LON_WGS84,
        "HDF5",
        progress=gdal.TermProgress_nocb,
    )

    minarea_deg2 = area2degrees(settings.satellite_min_area_km2)
    detector = detectors.LessThan(settings.satellite_threshold_kelvin, minarea_deg2)
    systems = detector.detect(grid)
    for system in systems:
        system.timestamp = timestamp

    descriptors.StatisticalDescriptor(stats=["min", "mean", "count"]).describe(grid, systems)

    resolution_km = settings.satellite_grid_resolution_km
    detected: list[DetectedSystem] = []
    for system in systems:
        lon, lat = system.getCentroid()
        count = system.attrs.get("count") or 0
        min_temp = system.attrs.get("min")
        if min_temp is None:
            continue
        detected.append(
            DetectedSystem(
                latitude=lat,
                longitude=lon,
                geometry_wkt=system.getGeomWKT(),
                min_brightness_temp_k=float(min_temp),
                area_km2=float(count) * (resolution_km**2),
            )
        )

    band = grid.GetRasterBand(1)
    png, width, height = _render_ir_image(grid.ReadAsArray(), band.GetNoDataValue())
    return _CycleArtifacts(systems=detected, image_png=png, image_width=width, image_height=height)


def _match_or_create(
    session: Session, detected: list[DetectedSystem], now: datetime
) -> tuple[list[ConvectiveWatch], list[ConvectiveWatch]]:
    """Update/create watches for ``detected``; return (touched, dissipated)."""
    active = list(
        session.scalars(select(ConvectiveWatch).where(ConvectiveWatch.is_active.is_(True)))
    )
    matched_ids: set[Any] = set()
    touched: list[ConvectiveWatch] = []

    for system in detected:
        best: ConvectiveWatch | None = None
        best_distance = _MATCH_DISTANCE_KM
        for watch in active:
            if watch.id in matched_ids:
                continue
            distance = haversine_km(
                system.latitude, system.longitude, watch.latitude, watch.longitude
            )
            if distance < best_distance:
                best, best_distance = watch, distance

        if best is not None:
            # Compute velocity from the watch's *previous* state before
            # overwriting it with the new detection.
            speed, direction = _velocity(best, system, now)
            best.detected_at = now
            best.latitude = system.latitude
            best.longitude = system.longitude
            best.centroid = WKTElement(f"POINT({system.longitude} {system.latitude})", srid=4326)
            best.geometry = WKTElement(system.geometry_wkt, srid=4326)
            best.min_brightness_temp_k = system.min_brightness_temp_k
            best.area_km2 = system.area_km2
            best.speed_kmh = speed
            best.direction_deg = direction
            matched_ids.add(best.id)
            touched.append(best)
        else:
            watch = ConvectiveWatch(
                first_detected_at=now,
                detected_at=now,
                latitude=system.latitude,
                longitude=system.longitude,
                centroid=WKTElement(f"POINT({system.longitude} {system.latitude})", srid=4326),
                geometry=WKTElement(system.geometry_wkt, srid=4326),
                min_brightness_temp_k=system.min_brightness_temp_k,
                area_km2=system.area_km2,
                is_active=True,
                is_mock=False,
                experimental=True,
            )
            session.add(watch)
            touched.append(watch)

    dissipated = [w for w in active if w.id not in matched_ids]
    for watch in dissipated:
        watch.is_active = False

    return touched, dissipated


def _velocity(
    previous: ConvectiveWatch, current: DetectedSystem, now: datetime
) -> tuple[float | None, float | None]:
    """Speed/direction from the watch's last known position, if recent enough."""
    from engine.geo import bearing_deg

    elapsed_hours = (now - previous.detected_at).total_seconds() / 3600.0
    if elapsed_hours <= 0 or elapsed_hours > 1.0:
        return None, None
    distance_km = haversine_km(
        previous.latitude, previous.longitude, current.latitude, current.longitude
    )
    speed = distance_km / elapsed_hours
    direction = bearing_deg(
        previous.latitude, previous.longitude, current.latitude, current.longitude
    )
    return round(speed, 1), round(direction, 1)


def _dedup_key(event: AlertEventType, location_id: Any, watch_id: Any) -> str:
    return f"{location_id}:{watch_id}:{event.value}"


def _emit_alert(
    session: Session,
    *,
    location: Location,
    watch: ConvectiveWatch,
    event: AlertEventType,
    title: str,
    message: str,
) -> bool:
    """Idempotent alert emission — same dedup_key pattern as pipeline_service.py."""
    dedup_key = _dedup_key(event, location.id, watch.id)
    already = session.scalars(
        select(Alert).where(Alert.tenant_id == location.tenant_id, Alert.dedup_key == dedup_key)
    ).first()
    if already is not None:
        return False

    alert = Alert(
        tenant_id=location.tenant_id,
        user_id=location.user_id,
        location_id=location.id,
        convective_watch_id=watch.id,
        event_type=event,
        level=_WATCH_LEVEL,
        title=title,
        message=message,
        dedup_key=dedup_key,
    )
    session.add(alert)
    session.flush()
    session.add(
        Notification(
            tenant_id=location.tenant_id,
            alert_id=alert.id,
            user_id=location.user_id,
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
        )
    )
    return True


def _decide_alerts(
    session: Session, touched: list[ConvectiveWatch], dissipated: list[ConvectiveWatch]
) -> int:
    locations = list(session.scalars(select(Location).where(Location.is_active.is_(True))))
    count = 0

    for watch in touched:
        for location in locations:
            distance = haversine_km(
                watch.latitude, watch.longitude, location.latitude, location.longitude
            )
            if distance > location.radius_km:
                continue
            emitted = _emit_alert(
                session,
                location=location,
                watch=watch,
                event=AlertEventType.SATELLITE_WATCH_DETECTED,
                title=f"Observação via satélite perto de {location.name}",
                message=(
                    f"Nuvem em resfriamento detectada por satélite a {distance:.0f} km "
                    f"(topo a {watch.min_brightness_temp_k:.0f} K) — sinal precoce, "
                    "não uma tempestade confirmada."
                ),
            )
            if emitted:
                count += 1

    for watch in dissipated:
        # Only tell locations that were actually told about this watch.
        alerted_location_ids = session.scalars(
            select(Alert.location_id).where(
                Alert.convective_watch_id == watch.id,
                Alert.event_type == AlertEventType.SATELLITE_WATCH_DETECTED,
            )
        ).all()
        for location in locations:
            if location.id not in alerted_location_ids:
                continue
            emitted = _emit_alert(
                session,
                location=location,
                watch=watch,
                event=AlertEventType.SATELLITE_WATCH_DISSIPATED,
                title=f"Observação via satélite dissipada perto de {location.name}",
                message="A formação em observação não é mais detectada pelo satélite.",
            )
            if emitted:
                count += 1

    return count


def _persist_image(
    session: Session, *, png: bytes, width: int, height: int, settings: Settings, now: datetime
) -> None:
    """Replace the current satellite frame — only the latest one is kept.

    A live overlay has no use for history, so each cycle deletes whatever
    was there before instead of accumulating rows (same "prune, don't
    accumulate" spirit as ``_prune_stale_watches``/``_prune_old_mock_cells``
    in ``pipeline_service.py``).
    """
    for stale in session.scalars(select(SatelliteImage)).all():
        session.delete(stale)
    lon_min, lat_min, lon_max, lat_max = settings.satellite_extent_bbox
    session.add(
        SatelliteImage(
            captured_at=now,
            bbox_lon_min=lon_min,
            bbox_lat_min=lat_min,
            bbox_lon_max=lon_max,
            bbox_lat_max=lat_max,
            band=settings.satellite_band,
            width=width,
            height=height,
            png_data=png,
            is_mock=False,
            experimental=True,
        )
    )


def _prune_stale_watches(session: Session, *, older_than: timedelta) -> None:
    cutoff = datetime.now(UTC) - older_than
    stale = session.scalars(
        select(ConvectiveWatch).where(
            ConvectiveWatch.is_active.is_(False), ConvectiveWatch.detected_at < cutoff
        )
    ).all()
    for watch in stale:
        session.delete(watch)


def run_satellite_detection_cycle(
    session: Session, *, settings: Settings | None = None, client: httpx.Client | None = None
) -> SatelliteCycleSummary:
    settings = settings or get_settings()
    if not settings.satellite_enabled:
        return SatelliteCycleSummary(enabled=False)

    own_client = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        items = _stac_search(client, settings, limit=1)
        if not items:
            logger.warning("no satellite items found for the configured extent/collection")
            return SatelliteCycleSummary(enabled=True)

        item = items[0]
        timestamp = _item_timestamp(item)
        href = _asset_href(item, settings.satellite_band)

        with tempfile.TemporaryDirectory(prefix="stormpulse-satellite-") as tmp:
            path = _download(client, href, Path(tmp))
            artifacts = _detect_systems(path, settings, timestamp)
    finally:
        if own_client:
            client.close()

    now = datetime.now(UTC)
    touched, dissipated = _match_or_create(session, artifacts.systems, now)
    session.flush()
    alerts = _decide_alerts(session, touched, dissipated)
    _prune_stale_watches(
        session, older_than=timedelta(hours=settings.satellite_max_watch_age_hours)
    )
    _persist_image(
        session,
        png=artifacts.image_png,
        width=artifacts.image_width,
        height=artifacts.image_height,
        settings=settings,
        now=timestamp,
    )

    return SatelliteCycleSummary(
        enabled=True,
        frames_downloaded=1,
        systems_detected=len(artifacts.systems),
        watches_active=len(touched),
        watches_dissipated=len(dissipated),
        alerts=alerts,
    )
