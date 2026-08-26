"""Storm cells, their temporal tracks, observations and per-location risk.

Storm cells are physical phenomena — global, not tenant-scoped. Risk is
computed per monitored location, so ``StormRisk`` carries a tenant.

Any value derived from simulated input carries ``is_mock=True``; any
non-validated heuristic carries ``experimental=True`` (see ADR-0005).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RiskLevel, StormSeverity, TrackTrend
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class StormCell(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "storm_cells"

    weather_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weather_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    # Cell footprint polygon and centroid point (WGS84).
    geometry: Mapped[Any] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326), nullable=True
    )
    centroid: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    max_reflectivity: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_reflectivity: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[StormSeverity] = mapped_column(
        Enum(StormSeverity, name="storm_severity", native_enum=True),
        nullable=False,
        default=StormSeverity.WEAK,
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tracks: Mapped[list[StormTrack]] = relationship(
        back_populates="storm_cell", cascade="all, delete-orphan"
    )


class StormTrack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Temporal grouping of observations for a single cell."""

    __tablename__ = "storm_tracks"

    storm_cell_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storm_cells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    storm_cell: Mapped[StormCell] = relationship(back_populates="tracks")
    observations: Mapped[list[StormObservation]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class StormObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single point-in-time observation along a track."""

    __tablename__ = "storm_observations"

    storm_track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storm_tracks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend: Mapped[TrackTrend | None] = mapped_column(
        Enum(TrackTrend, name="track_trend", native_enum=True), nullable=True
    )

    track: Mapped[StormTrack] = relationship(back_populates="observations")


class StormRisk(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Materialized risk assessment of a storm for a monitored location.

    Mirrors the ``StormRiskEngine`` output contract. Values may be MOCK and/or
    experimental in early phases — flagged explicitly, never presented as real.
    """

    __tablename__ = "storm_risks"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storm_cell_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storm_cells.id", ondelete="SET NULL"), nullable=True, index=True
    )
    severity: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", native_enum=True), nullable=False
    )
    rain_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wind_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hail_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lightning_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    storm_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    storm_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    experimental: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Rule provenance / score breakdown, for auditability.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Short natural-language explanation of the numbers above, generated by
    # Claude (FASE 9, ADR-0060) — never a second source of risk, only a
    # rephrasing of this same row's own columns. NULL when
    # ANTHROPIC_API_KEY isn't configured, generation is still pending
    # (async, dispatched right after this row is created), or severity was
    # GREEN (not worth explaining).
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
