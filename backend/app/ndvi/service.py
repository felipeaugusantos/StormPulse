"""Read-side service for historical vegetation-index intelligence."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import VegetationIndex
from app.ndvi.analytics import MINIMUM_ANOMALY_HISTORY, HistoricalValue, calculate_anomaly
from app.ndvi.analytics import has_persistent_drop as detect_persistent_drop
from app.ndvi.models import NdviReading
from app.ndvi.provider import VigorZone
from app.ndvi.schemas import (
    VegetationAnomalyOut,
    VegetationComparisonOut,
    VegetationReadingOut,
    VegetationSeriesOut,
)


def reading_out(row: NdviReading) -> VegetationReadingOut:
    try:
        zones = [VigorZone.model_validate(item) for item in json.loads(row.vigor_zones_json)]
    except (json.JSONDecodeError, TypeError, ValueError):
        zones = []
    return VegetationReadingOut(
        id=str(row.id),
        observed_at=row.observed_at,
        index_name=VegetationIndex(row.index_name),
        value_mean=row.ndvi_mean,
        source_name=row.source_name,
        valid_pixel_percent=row.valid_pixel_percent,
        cloud_cover_percent=row.cloud_cover_percent,
        quality=row.quality,
        reliable=row.reliable,
        vigor_zones=zones,
        is_mock=row.is_mock,
    )


async def get_series(
    session: AsyncSession,
    *,
    location_id: uuid.UUID,
    index_name: VegetationIndex,
    days: int,
) -> VegetationSeriesOut:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = list(
        (
            await session.execute(
                select(NdviReading)
                .where(
                    NdviReading.location_id == location_id,
                    NdviReading.index_name == index_name.value,
                    NdviReading.observed_at >= cutoff,
                )
                .order_by(NdviReading.observed_at.asc())
            )
        )
        .scalars()
        .all()
    )
    output = [reading_out(row) for row in rows]
    current = output[-1] if output else None
    history = [HistoricalValue(item.value_mean, item.reliable) for item in output[:-1]]
    anomaly = calculate_anomaly(
        HistoricalValue(current.value_mean, current.reliable) if current else None,
        history,
    )
    return VegetationSeriesOut(
        location_id=str(location_id),
        index_name=index_name,
        current=current,
        series=output,
        anomaly=VegetationAnomalyOut(
            status=anomaly.status,
            minimum_history=MINIMUM_ANOMALY_HISTORY,
            baseline_count=anomaly.baseline_count,
            baseline_mean=anomaly.baseline_mean,
            difference=anomaly.difference,
            percent_difference=anomaly.percent_difference,
            z_score=anomaly.z_score,
        ),
        persistent_drop=detect_persistent_drop(
            [HistoricalValue(item.value_mean, item.reliable) for item in output]
        ),
    )


def compare_readings(
    *,
    location_id: uuid.UUID,
    index_name: VegetationIndex,
    series: list[VegetationReadingOut],
    older_date: date | None,
    newer_date: date | None,
) -> VegetationComparisonOut | None:
    reliable = [item for item in series if item.reliable]

    def on_date(target: date) -> VegetationReadingOut | None:
        return next((item for item in reliable if item.observed_at.date() == target), None)

    older = on_date(older_date) if older_date else (reliable[-2] if len(reliable) >= 2 else None)
    newer = on_date(newer_date) if newer_date else (reliable[-1] if reliable else None)
    if older is None or newer is None or older.observed_at >= newer.observed_at:
        return None
    change = newer.value_mean - older.value_mean
    percent = change / abs(older.value_mean) * 100 if older.value_mean != 0 else None
    return VegetationComparisonOut(
        location_id=str(location_id),
        index_name=index_name,
        older=older,
        newer=newer,
        absolute_change=round(change, 4),
        percent_change=round(percent, 1) if percent is not None else None,
    )


def series_csv(series: VegetationSeriesOut) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        [
            "index",
            "observed_at",
            "value_mean",
            "source",
            "valid_pixel_percent",
            "cloud_cover_percent",
            "quality",
            "reliable",
            "is_mock",
        ]
    )
    for item in series.series:
        writer.writerow(
            [
                item.index_name.value,
                item.observed_at.isoformat(),
                item.value_mean,
                item.source_name,
                item.valid_pixel_percent,
                item.cloud_cover_percent,
                item.quality.value,
                str(item.reliable).lower(),
                str(item.is_mock).lower(),
            ]
        )
    return stream.getvalue()
