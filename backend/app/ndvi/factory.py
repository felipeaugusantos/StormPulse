"""NDVI provider selection (FASE 29, ADR-0053).

Only two tiers — unlike weather (mock/INMET/CPTEC/Open-Meteo with a
fallback chain), there's exactly one real NDVI source. Mock when
`ndvi_enabled=false` (the default) or credentials aren't set; real
otherwise.
"""

from __future__ import annotations

from app.core.config import Settings
from app.ndvi.mock import MockNdviProvider
from app.ndvi.provider import NdviProvider
from app.ndvi.sentinel_hub import SentinelHubNdviProvider


def get_ndvi_provider(settings: Settings) -> NdviProvider:
    if not settings.ndvi_enabled:
        return MockNdviProvider()
    return SentinelHubNdviProvider(settings)
