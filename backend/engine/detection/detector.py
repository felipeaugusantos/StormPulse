"""Cell detection (FASE 6).

Turns raw provider cells into detected storm cells with a coarse, deterministic
severity. EXPERIMENTAL placeholder — reflectivity/area only, never supercell
identification (ADR-0005).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.enums import StormSeverity
from engine.config import DEFAULT_DETECTION, DetectionConfig
from engine.geo import destination_point
from engine.provider_types import RawCellInput


@dataclass(frozen=True)
class DetectedCell:
    """A detected storm cell (engine result, not yet persisted)."""

    detected_at: datetime
    latitude: float
    longitude: float
    max_reflectivity: float | None
    average_reflectivity: float | None
    area_km2: float | None
    severity: StormSeverity
    is_mock: bool
    experimental: bool = True
    footprint_wkt: str | None = None
    centroid_wkt: str | None = None


def classify_severity(max_reflectivity: float | None, cfg: DetectionConfig) -> StormSeverity:
    """Coarse severity from peak reflectivity. EXPERIMENTAL — see module docstring."""
    dbz = max_reflectivity or 0.0
    if dbz >= cfg.severe_dbz:
        return StormSeverity.SEVERE
    if dbz >= cfg.strong_dbz:
        return StormSeverity.STRONG
    if dbz >= cfg.moderate_dbz:
        return StormSeverity.MODERATE
    return StormSeverity.WEAK


def _square_footprint_wkt(lat: float, lon: float, half_km: float) -> str:
    """A small axis-aligned-ish square polygon around a centroid (WKT, lon lat)."""
    n = destination_point(lat, lon, 0, half_km)
    e = destination_point(lat, lon, 90, half_km)
    s = destination_point(lat, lon, 180, half_km)
    w = destination_point(lat, lon, 270, half_km)
    ring = [
        (w[1], n[0]),  # NW
        (e[1], n[0]),  # NE
        (e[1], s[0]),  # SE
        (w[1], s[0]),  # SW
        (w[1], n[0]),  # close
    ]
    coords = ", ".join(f"{x} {y}" for x, y in ring)
    return f"POLYGON(({coords}))"


class CellDetector:
    """Detects storm cells from a frame's raw cells."""

    def __init__(self, config: DetectionConfig = DEFAULT_DETECTION) -> None:
        self.config = config

    def detect(
        self, *, captured_at: datetime, raw_cells: list[RawCellInput], is_mock: bool
    ) -> list[DetectedCell]:
        detected: list[DetectedCell] = []
        for cell in raw_cells:
            if (cell.max_reflectivity or 0.0) < self.config.min_reflectivity_dbz:
                continue
            detected.append(
                DetectedCell(
                    detected_at=captured_at,
                    latitude=cell.latitude,
                    longitude=cell.longitude,
                    max_reflectivity=cell.max_reflectivity,
                    average_reflectivity=cell.average_reflectivity,
                    area_km2=cell.area_km2,
                    severity=classify_severity(cell.max_reflectivity, self.config),
                    is_mock=is_mock,
                    footprint_wkt=_square_footprint_wkt(
                        cell.latitude, cell.longitude, self.config.footprint_half_km
                    ),
                    centroid_wkt=f"POINT({cell.longitude} {cell.latitude})",
                )
            )
        return detected
