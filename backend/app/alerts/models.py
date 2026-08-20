"""Alert model — an event-driven, deduplicated notification decision.

``dedup_key`` enforces idempotency: the alert engine (FASE 9) computes a
stable key per (user, location, storm, meaningful-state) so the same alert is
never emitted twice. Uniqueness is scoped per tenant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AlertEventType, RiskLevel
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Alert(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("tenant_id", "dedup_key", name="uq_alert_tenant_dedup"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storm_cell_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storm_cells.id", ondelete="SET NULL"), nullable=True, index=True
    )
    storm_risk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storm_risks.id", ondelete="SET NULL"), nullable=True
    )
    # Satellite-derived alerts (FASE 16) point here instead of storm_cell_id.
    convective_watch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("convective_watches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[AlertEventType] = mapped_column(
        Enum(AlertEventType, name="alert_event_type", native_enum=True), nullable=False
    )
    level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", native_enum=True, create_type=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
