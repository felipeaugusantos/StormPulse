"""Weather source registry and ingested radar frames.

Sources are global (not tenant-scoped): a physical radar or official warning
feed is shared. The MOCK kind must always be explicit (never presented as real
data).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import WeatherSourceKind
from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WeatherSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "weather_sources"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    kind: Mapped[WeatherSourceKind] = mapped_column(
        Enum(WeatherSourceKind, name="weather_source_kind", native_enum=True), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class RadarFrame(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "radar_frames"

    weather_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("weather_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Explicit MOCK flag — mirrors the source kind for fast filtering.
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
