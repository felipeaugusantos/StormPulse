"""NDVI readings per talhão (FASE 29, ADR-0053).

Tenant-scoped through `location_id` (same shape as `AlertPreference`) —
unlike `SatelliteImage`/`ConvectiveWatch`, which are global weather
phenomena, an NDVI reading only ever means something in the context of one
specific talhão someone drew a boundary for.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, LargeBinary, UniqueConstraint
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


class NdviImage(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """The most recent colored NDVI visualization (PNG) for one talhão —
    item "imagem do talhão" in the weekly report.

    Only the latest is ever kept per location (unique `location_id`,
    replaced each pipeline cycle) — same "prune, don't accumulate" spirit
    as ``SatelliteImage`` (``app/satellite/models.py``), just scoped per
    talhão instead of being one global row: a report only ever needs to
    show the current picture, not a gallery of every past one, and a
    rendered image is heavy enough that accumulating one per cycle
    forever would be a real storage cost for no benefit.
    """

    __tablename__ = "ndvi_images"
    __table_args__ = (UniqueConstraint("location_id", name="uq_ndvi_image_location"),)

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    png_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
