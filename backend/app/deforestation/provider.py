"""DeforestationProvider abstraction — checks a talhão's drawn boundary
against INPE's own deforestation-alert layers (item DETER).

Unlike `NdviProvider` (a continuous numeric reading), a deforestation check
doesn't have a single "the source failed" outcome — DETER (Amazônia) and
PRODES-Cerrado are two independent WFS layers, either can succeed or fail on
its own, and even a fully successful check for a talhão outside both
biomes' extents honestly returns zero alerts (that's not the same claim as
"nenhum alerta" for a talhão actually inside a covered biome — see
`DeforestationCheckResult.checked_sources`). Modeled as a result object
instead of an exception for that reason: "some sources unreachable this
cycle" is a normal, storable outcome, not a hard failure.
"""

from __future__ import annotations

import abc
from datetime import date

from pydantic import BaseModel

# Human-facing identifiers for the two layers a check can hit — used both
# as `DeforestationAlert.source` and in `DeforestationCheckResult`'s
# checked/unavailable lists, so the report can say exactly which registries
# were actually consulted.
DETER_AMZ_SOURCE = "DETER-AMZ"
PRODES_CERRADO_SOURCE = "PRODES-CERRADO"


class DeforestationAlert(BaseModel):
    source: str
    classname: str
    detected_at: date | None
    area_ha: float | None
    municipio: str | None
    uf: str | None


class DeforestationCheckResult(BaseModel):
    # Sources that responded successfully this attempt (possibly with zero
    # alerts — that's still a successful, reportable check).
    checked_sources: list[str]
    # Sources that were attempted but failed (timeout, HTTP error) — the
    # caller (the pipeline) must never let this silently look like "checked,
    # no alerts" for these; see `workers/deforestation_pipeline.py`.
    unavailable_sources: list[str]
    alerts: list[DeforestationAlert]


class DeforestationProvider(abc.ABC):
    """Interface every deforestation-registry source must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    async def check(
        self, boundary_geojson: str, *, lookback_years: float
    ) -> DeforestationCheckResult:
        """`boundary_geojson` is a GeoJSON Polygon serialized as a JSON
        string — the exact same format `Location.boundary_geojson` is
        stored/validated in (see `app.locations.schemas`)."""
        ...

    async def aclose(self) -> None:  # pragma: no cover - overridden when needed
        return None
