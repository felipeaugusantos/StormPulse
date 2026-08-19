"""Decoupled input types for the engine.

The engine must not depend on any weather source. A worker adapts a provider's
raw output into these plain structures before feeding the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RawCellInput:
    latitude: float
    longitude: float
    max_reflectivity: float | None = None
    average_reflectivity: float | None = None
    area_km2: float | None = None


@dataclass(frozen=True)
class FrameInput:
    """A single frame: a timestamp, its raw cells and a MOCK flag."""

    captured_at: datetime
    raw_cells: list[RawCellInput]
    is_mock: bool
