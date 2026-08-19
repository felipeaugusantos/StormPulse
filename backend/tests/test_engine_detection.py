"""Tests for cell detection and severity classification."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import StormSeverity
from engine.config import DEFAULT_DETECTION
from engine.detection.detector import CellDetector, classify_severity
from engine.provider_types import RawCellInput


def test_classify_severity_buckets() -> None:
    cfg = DEFAULT_DETECTION
    assert classify_severity(30, cfg) is StormSeverity.WEAK
    assert classify_severity(42, cfg) is StormSeverity.MODERATE
    assert classify_severity(52, cfg) is StormSeverity.STRONG
    assert classify_severity(60, cfg) is StormSeverity.SEVERE
    assert classify_severity(None, cfg) is StormSeverity.WEAK


def test_detector_filters_weak_cells() -> None:
    detector = CellDetector()
    cells = [
        RawCellInput(latitude=-23.5, longitude=-46.6, max_reflectivity=20),  # below min
        RawCellInput(latitude=-23.6, longitude=-46.7, max_reflectivity=57),  # severe
    ]
    detected = detector.detect(captured_at=datetime.now(UTC), raw_cells=cells, is_mock=True)
    assert len(detected) == 1
    cell = detected[0]
    assert cell.severity is StormSeverity.SEVERE
    assert cell.is_mock is True
    assert cell.experimental is True
    assert cell.centroid_wkt == "POINT(-46.7 -23.6)"
    assert cell.footprint_wkt is not None and cell.footprint_wkt.startswith("POLYGON")
