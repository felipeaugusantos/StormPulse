from datetime import UTC, datetime, timedelta

from app.core.enums import ImageQuality, VegetationIndex
from app.ndvi.analytics import (
    HistoricalValue,
    calculate_anomaly,
    has_persistent_drop,
    quality_from_valid_pixels,
)
from app.ndvi.schemas import VegetationAnomalyOut, VegetationReadingOut, VegetationSeriesOut
from app.ndvi.service import compare_readings, series_csv


def _reading(days_ago: int, value: float, *, reliable: bool = True) -> VegetationReadingOut:
    return VegetationReadingOut(
        id=str(days_ago),
        observed_at=datetime.now(UTC) - timedelta(days=days_ago),
        index_name=VegetationIndex.NDVI,
        value_mean=value,
        source_name="Copernicus Sentinel Hub",
        valid_pixel_percent=90 if reliable else 40,
        cloud_cover_percent=10 if reliable else 60,
        quality=ImageQuality.HIGH if reliable else ImageQuality.LOW,
        reliable=reliable,
        vigor_zones=[],
        is_mock=False,
    )


def test_quality_marks_cloud_obscured_acquisition_as_low_and_unreliable() -> None:
    assert quality_from_valid_pixels(85) == ImageQuality.HIGH
    assert quality_from_valid_pixels(65) == ImageQuality.MEDIUM
    assert quality_from_valid_pixels(59.9) == ImageQuality.LOW


def test_anomaly_requires_five_reliable_historical_acquisitions() -> None:
    history = [HistoricalValue(0.5 + i / 100, True) for i in range(4)]
    result = calculate_anomaly(HistoricalValue(0.2, True), history)
    assert result.status == "insufficient_history"
    assert result.baseline_mean is None


def test_cloudy_points_do_not_enter_anomaly_baseline() -> None:
    history = [HistoricalValue(0.6, True) for _ in range(5)]
    history.append(HistoricalValue(-0.9, False))
    result = calculate_anomaly(HistoricalValue(0.3, True), history)
    assert result.baseline_count == 5
    assert result.baseline_mean == 0.6
    assert result.status == "below_expected"


def test_unreliable_current_value_never_becomes_an_anomaly() -> None:
    result = calculate_anomaly(
        HistoricalValue(0.1, False), [HistoricalValue(0.7, True) for _ in range(8)]
    )
    assert result.status == "insufficient_history"


def test_persistent_drop_requires_three_reliable_decreasing_points() -> None:
    assert has_persistent_drop(
        [HistoricalValue(0.70, True), HistoricalValue(0.64, True), HistoricalValue(0.58, True)]
    )
    assert not has_persistent_drop(
        [HistoricalValue(0.70, True), HistoricalValue(0.30, False), HistoricalValue(0.58, True)]
    )
    assert not has_persistent_drop(
        [HistoricalValue(0.70, True), HistoricalValue(0.68, True), HistoricalValue(0.66, True)]
    )


def test_comparison_uses_two_latest_reliable_dates_and_ignores_cloudy_scene() -> None:
    readings = [_reading(10, 0.5), _reading(5, 0.1, reliable=False), _reading(1, 0.6)]
    comparison = compare_readings(
        location_id=__import__("uuid").uuid4(),
        index_name=VegetationIndex.NDVI,
        series=readings,
        older_date=None,
        newer_date=None,
    )
    assert comparison is not None
    assert comparison.older.value_mean == 0.5
    assert comparison.newer.value_mean == 0.6
    assert comparison.absolute_change == 0.1


def test_csv_contains_quality_source_and_cloud_metadata() -> None:
    reading = _reading(1, 0.6)
    series = VegetationSeriesOut(
        location_id="location",
        index_name=VegetationIndex.NDVI,
        current=reading,
        series=[reading],
        anomaly=VegetationAnomalyOut(
            status="insufficient_history",
            minimum_history=5,
            baseline_count=0,
            baseline_mean=None,
            difference=None,
            percent_difference=None,
            z_score=None,
        ),
        persistent_drop=False,
    )
    exported = series_csv(series)
    assert "source" in exported
    assert "cloud_cover_percent" in exported
    assert "Copernicus Sentinel Hub" in exported
