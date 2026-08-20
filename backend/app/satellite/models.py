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
from sqlalchemy import Boolean, DateTime, Float
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
