"""End-to-end engine pipeline test over synthetic frames."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from engine.pipeline import StormEngine
from engine.provider_types import FrameInput, RawCellInput

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _frame(lat: float, lon: float, minute: int) -> FrameInput:
    return FrameInput(
        captured_at=T0 + timedelta(minutes=minute),
        raw_cells=[RawCellInput(latitude=lat, longitude=lon, max_reflectivity=52.0)],
        is_mock=True,
    )


def test_pipeline_tracks_one_drifting_cell() -> None:
    frames = [_frame(-24.0, -46.6, 0), _frame(-23.9, -46.6, 5), _frame(-23.8, -46.6, 10)]
    result = StormEngine().process(frames)
    assert len(result) == 1
    tracked = result[0]
    assert len(tracked.track.observations) == 3
    assert tracked.trajectory is not None
    assert tracked.trajectory.direction_label == "N"


def test_pipeline_orders_unsorted_frames() -> None:
    frames = [_frame(-23.8, -46.6, 10), _frame(-24.0, -46.6, 0), _frame(-23.9, -46.6, 5)]
    result = StormEngine().process(frames)
    assert len(result) == 1
    times = [o.detected_at for o in result[0].track.observations]
    assert times == sorted(times)
