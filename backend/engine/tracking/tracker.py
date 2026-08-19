"""Temporal association of cells across frames (FASE 7).

A simple, explicitly-modular nearest-neighbour tracker: each detected cell in a
new frame extends the open track whose last centroid is closest, within a
distance threshold; otherwise it starts a new track. This is intentionally
replaceable by a better method (e.g. TITAN-style) behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from engine.config import DEFAULT_TRACKING, TrackingConfig
from engine.detection.detector import DetectedCell
from engine.geo import haversine_km


@dataclass
class Track:
    """An ordered sequence of observations of one storm cell over time."""

    observations: list[DetectedCell] = field(default_factory=list)

    @property
    def last(self) -> DetectedCell:
        return self.observations[-1]

    @property
    def started_at(self) -> datetime:
        return self.observations[0].detected_at

    @property
    def last_observed_at(self) -> datetime:
        return self.observations[-1].detected_at

    def add(self, cell: DetectedCell) -> None:
        self.observations.append(cell)


class TrackBuilder:
    """Builds tracks from time-ordered frames of detected cells."""

    def __init__(self, config: TrackingConfig = DEFAULT_TRACKING) -> None:
        self.config = config

    def build(self, frames: list[list[DetectedCell]]) -> list[Track]:
        """Associate cells across frames (frames must be time-ordered)."""
        tracks: list[Track] = []
        for frame in frames:
            self._consume_frame(tracks, frame)
        return tracks

    def _consume_frame(self, tracks: list[Track], frame: list[DetectedCell]) -> None:
        unmatched = list(frame)
        # Only tracks not yet extended in this frame are candidates.
        for track in tracks:
            if not unmatched:
                break
            best_idx = self._nearest(track.last, unmatched)
            if best_idx is not None:
                track.add(unmatched.pop(best_idx))
        # Leftovers begin new tracks.
        for cell in unmatched:
            tracks.append(Track(observations=[cell]))

    def _nearest(self, ref: DetectedCell, candidates: list[DetectedCell]) -> int | None:
        best_idx: int | None = None
        best_dist = self.config.max_association_km
        for i, cell in enumerate(candidates):
            d = haversine_km(ref.latitude, ref.longitude, cell.latitude, cell.longitude)
            if d <= best_dist:
                best_dist = d
                best_idx = i
        return best_idx
