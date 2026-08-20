"""Convective watches — satellite-derived precursor signals (FASE 16).

A cold, growing cloud top (infrared brightness temperature) is a *different*
kind of signal from a confirmed ``StormCell`` (radar reflectivity / rain
rate): it's a precursor, not a measurement of precipitation already
happening. Kept in its own table rather than reusing ``StormCell`` so we
never have to fabricate a fake reflectivity value from a temperature (see
ADR-0009). Global like ``StormCell`` — not tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, Float, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ConvectiveWatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "convective_watches"

    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    centroid: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    geometry: Mapped[Any] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326), nullable=True
    )
    min_brightness_temp_k: Mapped[float] = mapped_column(Float, nullable=False)
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Always real satellite data (no mock satellite provider exists), but
    # the technique itself is unvalidated meteorologically — see ADR-0005.
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SatelliteImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The most recent rendered satellite IR frame (FASE 18).

    Only the latest frame is ever kept — see ``workers.satellite_pipeline
    ._persist_image``, which deletes any existing row before inserting a new
    one each cycle. This is a *display* image (downsampled, grayscale IR
    convention), not the scientific raw grid — the real measurements live on
    ``ConvectiveWatch`` rows instead.
    """

    __tablename__ = "satellite_images"

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    bbox_lon_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_lat_min: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_lon_max: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_lat_max: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    png_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
