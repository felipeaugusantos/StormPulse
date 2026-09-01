"""Unit tests for the satellite frame's display-PNG rendering (FASE 18,
enhanced-IR color ramp added in ADR-0076).

``_render_ir_image`` is a pure function (array in, PNG bytes out) — no GDAL,
no network — but it does need numpy/Pillow, which live in the ``satellite``
extra, not the base ``dev`` install this CI uses (see
``backend/pyproject.toml``). Skipped rather than failed when that extra
isn't installed — same reasoning as the GDAL-dependent detection step
documented in ``test_satellite_pipeline.py``/ADR-0009.
"""

from __future__ import annotations

from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from workers.satellite_pipeline import (  # noqa: E402
    _COLOR_RAMP_RGB,
    _COLOR_RAMP_STOPS_K,
    _IMAGE_MAX_DIMENSION,
    _IMAGE_TEMP_WARM_K,
    _render_ir_image,
)


def _decode(png: bytes) -> Any:
    import io

    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_warm_pixels_stay_plain_grayscale() -> None:
    """Above the color ramp's warmest anchor (228.15K, "fraca" threshold) —
    ordinary sky/non-convective cloud — rendering must be unchanged from
    before this feature: pure grayscale, R == G == B."""
    warm = _COLOR_RAMP_STOPS_K[-1] + 20.0  # comfortably above the ramp, still colder than WARM_K
    temps = np.array(
        [[warm, _IMAGE_TEMP_WARM_K], [warm, _IMAGE_TEMP_WARM_K]],
        dtype=np.float32,
    )
    png, width, height = _render_ir_image(temps, nodata=None)
    assert width == 2 and height == 2

    decoded = _decode(png)
    for pixel in (decoded[0, 0], decoded[0, 1], decoded[1, 0]):
        assert pixel[0] == pixel[1] == pixel[2]
    cold_gray = decoded[0, 0]
    warm_gray = decoded[0, 1]
    assert cold_gray[0] > warm_gray[0]  # colder-but-still-warm-band is brighter
    assert cold_gray[3] == 255 and warm_gray[3] == 255


def test_color_ramp_matches_the_convective_watch_severity_thresholds() -> None:
    """The four anchor temperatures are the exact Kelvin equivalents of
    `convectiveIntensity`'s Celsius cutoffs (web/src/format.ts) — moderada/
    forte/severa must render as the documented yellow/orange/red, and the
    coldest sampled anchor as the deepest color, never grayscale."""
    temps = np.array([list(_COLOR_RAMP_STOPS_K)], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=None)

    decoded = _decode(png)
    for i, expected_rgb in enumerate(_COLOR_RAMP_RGB):
        pixel = decoded[0, i]
        assert tuple(pixel[:3]) == expected_rgb
        assert pixel[3] == 255


def test_color_ramp_interpolates_smoothly_between_anchors() -> None:
    # Midpoint between the "forte" (218.15K) and "severa" (208.15K) anchors
    # must land strictly between their two colors on every channel, not
    # jump straight to one or the other.
    midpoint = (218.15 + 208.15) / 2
    temps = np.array([[midpoint]], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=None)

    decoded = _decode(png)[0, 0]
    forte_rgb = dict(zip(_COLOR_RAMP_STOPS_K, _COLOR_RAMP_RGB, strict=True))[218.15]
    severa_rgb = dict(zip(_COLOR_RAMP_STOPS_K, _COLOR_RAMP_RGB, strict=True))[208.15]
    for channel in range(3):
        low, high = sorted((forte_rgb[channel], severa_rgb[channel]))
        assert low <= decoded[channel] <= high


def test_nodata_pixel_is_transparent() -> None:
    temps = np.array([[250.0, -999.0]], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=-999.0)

    decoded = _decode(png)
    assert decoded[0, 0][3] == 255  # valid pixel: opaque
    assert decoded[0, 1][3] == 0  # nodata pixel: transparent


def test_out_of_range_temperatures_clip_instead_of_wrapping() -> None:
    # Way colder/warmer than the configured range must still clip to a
    # fixed value, not wrap around or produce out-of-range values — colder
    # than the coldest color anchor clips to that anchor's own color
    # (never white), warmer than the grayscale span clips to pure black.
    temps = np.array([[100.0, 400.0]], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=None)

    decoded = _decode(png)
    assert tuple(decoded[0, 0][:3]) == _COLOR_RAMP_RGB[0]  # extremely cold
    assert tuple(decoded[0, 1][:3]) == (0, 0, 0)  # extremely warm -> fully dark


def test_large_grid_is_downsampled() -> None:
    size = _IMAGE_MAX_DIMENSION + 400
    temps = np.full((size, size), 250.0, dtype=np.float32)
    _, width, height = _render_ir_image(temps, nodata=None)
    assert width <= _IMAGE_MAX_DIMENSION
    assert height <= _IMAGE_MAX_DIMENSION
