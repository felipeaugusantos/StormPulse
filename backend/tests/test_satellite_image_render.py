"""Unit tests for the satellite frame's display-PNG rendering (FASE 18).

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
    _IMAGE_MAX_DIMENSION,
    _IMAGE_TEMP_COLD_K,
    _IMAGE_TEMP_WARM_K,
    _render_ir_image,
)


def _decode(png: bytes) -> Any:
    import io

    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def test_cold_pixel_is_bright_warm_pixel_is_dark() -> None:
    # Standard inverted-IR convention: cold cloud top -> bright, warm
    # surface -> dark. A 2x2 grid, no nodata.
    temps = np.array(
        [[_IMAGE_TEMP_COLD_K, _IMAGE_TEMP_WARM_K], [_IMAGE_TEMP_WARM_K, _IMAGE_TEMP_COLD_K]],
        dtype=np.float32,
    )
    png, width, height = _render_ir_image(temps, nodata=None)
    assert width == 2 and height == 2

    decoded = _decode(png)
    cold_pixel = decoded[0, 0]
    warm_pixel = decoded[0, 1]
    assert cold_pixel[0] > warm_pixel[0]  # cold is brighter (grayscale R channel)
    assert cold_pixel[3] == 255  # fully opaque, both valid
    assert warm_pixel[3] == 255


def test_nodata_pixel_is_transparent() -> None:
    temps = np.array([[250.0, -999.0]], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=-999.0)

    decoded = _decode(png)
    assert decoded[0, 0][3] == 255  # valid pixel: opaque
    assert decoded[0, 1][3] == 0  # nodata pixel: transparent


def test_out_of_range_temperatures_clip_instead_of_wrapping() -> None:
    # Way colder/warmer than the configured range must still clip to 0/255,
    # not wrap around or produce out-of-range values.
    temps = np.array([[100.0, 400.0]], dtype=np.float32)
    png, _, _ = _render_ir_image(temps, nodata=None)

    decoded = _decode(png)
    assert decoded[0, 0][0] == 255  # extremely cold -> fully bright
    assert decoded[0, 1][0] == 0  # extremely warm -> fully dark


def test_large_grid_is_downsampled() -> None:
    size = _IMAGE_MAX_DIMENSION + 400
    temps = np.full((size, size), 250.0, dtype=np.float32)
    _, width, height = _render_ir_image(temps, nodata=None)
    assert width <= _IMAGE_MAX_DIMENSION
    assert height <= _IMAGE_MAX_DIMENSION
