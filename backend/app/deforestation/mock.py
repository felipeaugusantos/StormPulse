"""MockDeforestationProvider — deterministic, no network.

Always reports both sources as successfully checked with zero alerts. It
exists to exercise the pipeline/report/PDF plumbing end-to-end without
depending on INPE's (real, occasionally flaky) public WFS — it must never
be presented to a user as an actual registry check.
"""

from __future__ import annotations

from app.deforestation.provider import (
    DETER_AMZ_SOURCE,
    PRODES_CERRADO_SOURCE,
    DeforestationCheckResult,
    DeforestationProvider,
)

_MOCK_NAME = "MOCK"


class MockDeforestationProvider(DeforestationProvider):
    @property
    def name(self) -> str:
        return _MOCK_NAME

    async def check(
        self, boundary_geojson: str, *, lookback_years: float
    ) -> DeforestationCheckResult:
        return DeforestationCheckResult(
            checked_sources=[DETER_AMZ_SOURCE, PRODES_CERRADO_SOURCE],
            unavailable_sources=[],
            alerts=[],
        )
