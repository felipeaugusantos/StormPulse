"""Deforestation provider selection (item DETER).

Mock when `deforestation_check_enabled=false` (the default); real
otherwise. Unlike NDVI, the real provider needs no credentials (both WFS
layers are public) — the flag exists purely so a fresh deploy doesn't
immediately start hammering INPE's own (occasionally flaky) public
infrastructure without an operator deciding to turn it on.
"""

from __future__ import annotations

from app.core.config import Settings
from app.deforestation.inpe import InpeDeforestationProvider
from app.deforestation.mock import MockDeforestationProvider
from app.deforestation.provider import DeforestationProvider


def get_deforestation_provider(settings: Settings) -> DeforestationProvider:
    if not settings.deforestation_check_enabled:
        return MockDeforestationProvider()
    return InpeDeforestationProvider(
        deter_amz_wfs_url=settings.deforestation_deter_amz_wfs_url,
        prodes_cerrado_wfs_url=settings.deforestation_prodes_cerrado_wfs_url,
        http_timeout_seconds=settings.deforestation_http_timeout_seconds,
    )
