"""Engine facade: detection → tracking → trajectory over a sequence of frames.

This is the seam a worker (FASE 10) will call. It stays pure and synchronous
(CPU-bound work belongs off the request path, in a worker).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.config import (
    DEFAULT_DETECTION,
    DEFAULT_TRACKING,
    DEFAULT_TRAJECTORY,
    DetectionConfig,
    TrackingConfig,
    TrajectoryConfig,
)
from engine.detection.detector import CellDetector
from engine.provider_types import FrameInput
from engine.tracking.tracker import Track, TrackBuilder
from engine.trajectory.estimator import Trajectory, estimate_trajectory


@dataclass(frozen=True)
class TrackedStorm:
    """A track plus its estimated trajectory (``None`` when < 2 observations)."""

    track: Track
    trajectory: Trajectory | None


class StormEngine:
    """Composes detection, tracking and trajectory estimation."""

    def __init__(
        self,
        *,
        detection: DetectionConfig = DEFAULT_DETECTION,
        tracking: TrackingConfig = DEFAULT_TRACKING,
        trajectory: TrajectoryConfig = DEFAULT_TRAJECTORY,
    ) -> None:
        self._detector = CellDetector(detection)
        self._tracker = TrackBuilder(tracking)
        self._trajectory_cfg = trajectory

    def process(self, frames: list[FrameInput]) -> list[TrackedStorm]:
        """Detect cells per frame, associate into tracks, estimate trajectories."""
        ordered = sorted(frames, key=lambda f: f.captured_at)
        detected_frames = [
            self._detector.detect(
                captured_at=frame.captured_at,
                raw_cells=frame.raw_cells,
                is_mock=frame.is_mock,
            )
            for frame in ordered
        ]
        tracks = self._tracker.build(detected_frames)
        return [
            TrackedStorm(track=t, trajectory=estimate_trajectory(t, self._trajectory_cfg))
            for t in tracks
        ]
