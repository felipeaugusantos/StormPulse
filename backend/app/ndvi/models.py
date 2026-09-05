"""Historical spectral-index readings and maps per talhão.

The legacy class/table names are retained for migration and API compatibility,
but rows now identify NDVI, NDRE, EVI, NDMI or NDWI explicitly (ADR-0083).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
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
    index_name: Mapped[str] = mapped_column(String(8), nullable=False, default="ndvi", index=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="unknown")
    cloud_cover_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality: Mapped[str] = mapped_column(String(12), nullable=False, default="high")
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vigor_zones_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NdviImage(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """The most recent colored NDVI visualization (PNG) for one talhão —
    item "imagem do talhão" in the weekly report.

    Historical images are retained per index/acquisition so users can
    compare dates. The pipeline deduplicates a repeated acquisition.
    """

    __tablename__ = "ndvi_images"
    __table_args__ = (
        UniqueConstraint(
            "location_id", "index_name", "observed_at", name="uq_vegetation_image_acquisition"
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    index_name: Mapped[str] = mapped_column(String(8), nullable=False, default="ndvi", index=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="unknown")
    cloud_cover_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality: Mapped[str] = mapped_column(String(12), nullable=False, default="high")
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    png_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
