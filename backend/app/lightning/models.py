"""Lightning strikes — from the API-REDEMET STSC product (FASE 23).

A live snapshot of recent atmospheric-discharge occurrences across Brazil,
not a historical record: ``workers/lightning_pipeline.py`` prunes any row
older than ``settings.lightning_retention_minutes`` every cycle (same
"instantaneous, always fresh" spirit as ``SatelliteImage``). Global like
``StormCell``/``ConvectiveWatch`` — not tenant-scoped, and a different kind
of signal from both: it's a real discharge detection, not a rain-rate or
cold-cloud-top proxy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LightningStrike(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lightning_strikes"

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
