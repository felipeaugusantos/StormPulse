"""Unit test for `render_weekly_report_pdf`'s NDVI image embedding (item
"imagem do talhão").

Real regression to guard: reportlab's `Image`/`ImageReader` flowable
hard-requires Pillow to decode raster bytes (`ImageReader._read_image`
calls `PIL.Image.open` directly — confirmed by reading reportlab's own
source, no pure-Python fallback exists). The `api` container used to ship
without Pillow (it was satellite-extra-only) — embedding a real PNG would
have raised at `doc.build()` time. Pillow is now a base dependency (see
pyproject.toml) specifically so this works; this test would have caught
the crash before it ever reached production. No Postgres/Redis needed —
`render_weekly_report_pdf` has no database or network access of its own.
"""

from __future__ import annotations

import struct
import zlib
from datetime import UTC, date, datetime

from app.deforestation.provider import DETER_AMZ_SOURCE, DeforestationAlert
from app.locations.pdf import render_weekly_report_pdf
from app.locations.schemas import DeforestationCheckOut, SoilMoistureOut, WeeklyReportOut


def _tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    size = 4
    row = bytes([0]) + bytes([80, 160, 80]) * size
    raw = row * size
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _report(**overrides: object) -> WeeklyReportOut:
    base: dict[str, object] = {
        "location_id": "5b3e4c9a-2f1b-4a8e-9c7d-1e2f3a4b5c6d",
        "location_name": "Talhão Teste",
        "crop": "soja",
        "area_ha": 12.34,
        "period_start": date(2026, 8, 21),
        "period_end": date(2026, 8, 27),
        "rainfall_total_mm": 15.5,
        "dry_days_count": 4,
        "alerts": [],
        "ndvi_readings": [],
        "generated_at": datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return WeeklyReportOut(**base)


def test_renders_a_real_pdf_without_an_ndvi_image() -> None:
    pdf_bytes = render_weekly_report_pdf(_report())
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_a_real_pdf_with_an_embedded_ndvi_image() -> None:
    pdf_bytes = render_weekly_report_pdf(_report(), ndvi_image_png=_tiny_png())
    assert pdf_bytes.startswith(b"%PDF")
    # The image is embedded as a raw XObject stream, not re-encoded as
    # readable text — just confirm the PDF grew meaningfully versus the
    # no-image case instead of asserting on exact byte content.
    without_image = render_weekly_report_pdf(_report())
    assert len(pdf_bytes) > len(without_image)


def test_renders_without_crashing_when_deforestation_was_never_checked() -> None:
    pdf_bytes = render_weekly_report_pdf(_report(deforestation=None))
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_the_deforestation_section_with_an_alert() -> None:
    report = _report(
        deforestation=DeforestationCheckOut(
            checked_sources=[DETER_AMZ_SOURCE],
            last_checked_at=datetime(2026, 8, 27, 6, 0, tzinfo=UTC),
            alerts=[
                DeforestationAlert(
                    source=DETER_AMZ_SOURCE,
                    classname="DESMATAMENTO_CR",
                    detected_at=date(2026, 7, 1),
                    area_ha=12.5,
                    municipio="obidos",
                    uf="PA",
                )
            ],
        )
    )
    pdf_bytes = render_weekly_report_pdf(report)
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_the_soil_moisture_section_when_present() -> None:
    report = _report(
        soil_moisture=SoilMoistureOut(
            observed_at=date(2026, 8, 27),
            surface_wetness_percent=33.0,
            root_zone_wetness_percent=46.0,
            profile_wetness_percent=46.0,
            is_mock=False,
        )
    )
    pdf_bytes = render_weekly_report_pdf(report)
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_without_crashing_when_soil_moisture_was_never_fetched() -> None:
    pdf_bytes = render_weekly_report_pdf(_report(soil_moisture=None))
    assert pdf_bytes.startswith(b"%PDF")
