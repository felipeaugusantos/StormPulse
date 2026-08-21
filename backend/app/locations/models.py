"""Monitored location and its per-type alert preferences."""

from __future__ import annotations

import uuid
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AlertType
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Location(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "locations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Free-form label: Casa, Trabalho, Escola, Fazenda, Empresa, Evento, Outros…
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    radius_km: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    # Talhão support (FASE 26): a location with a parent is a plot inside
    # the parent farm — reuses every weather/agro endpoint as-is (they're
    # all keyed by location id/lat-lon already). Only one level deep —
    # a plot cannot itself have children (enforced in the router).
    parent_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Free-form crop label (soja, milho, café...) — only meaningful for a
    # plot, but not enforced at the DB level (a farm without plots may
    # still want to record what it grows).
    crop: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # PostGIS geography point (WGS84) for proximity queries (ST_DWithin).
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    alert_preferences: Mapped[list[AlertPreference]] = relationship(
        back_populates="location",
        cascade="all, delete-orphan",
    )


class AlertPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_preferences"
    __table_args__ = (
        UniqueConstraint("location_id", "alert_type", name="uq_alert_pref_location_type"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type", native_enum=True), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    location: Mapped[Location] = relationship(back_populates="alert_preferences")
