"""Deforestation-check results per talhão (item DETER).

One row per (location, source) — DETER-AMZ and PRODES-Cerrado are
independent layers, and a bad cycle for one must never erase the other's
last successful result (same "only overwrite on success" spirit as
``NdviImage``, applied per source instead of per talhão since here there
are two independent upstream registries instead of one).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DeforestationCheck(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "deforestation_checks"
    __table_args__ = (
        UniqueConstraint("location_id", "source", name="uq_deforestation_check_location_source"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "DETER-AMZ" | "PRODES-CERRADO" (app.deforestation.provider).
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON-serialized list[DeforestationAlert] for this source only — kept
    # as opaque text (same pattern as `Location.boundary_geojson`) since
    # it's only ever re-parsed by app.locations.service, never queried on.
    alerts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
