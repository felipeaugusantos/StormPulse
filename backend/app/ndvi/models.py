"""NDVI readings per talhão (FASE 29, ADR-0053).

Tenant-scoped through `location_id` (same shape as `AlertPreference`) —
unlike `SatelliteImage`/`ConvectiveWatch`, which are global weather
phenomena, an NDVI reading only ever means something in the context of one
specific talhão someone drew a boundary for.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class NdviReading(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "ndvi_readings"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ndvi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    valid_pixel_percent: Mapped[float] = mapped_column(Float, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
