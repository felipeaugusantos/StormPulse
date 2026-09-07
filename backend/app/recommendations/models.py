"""Recommended actions — data model (Fase 5, ADR-0089).

One tenant-scoped table, additive alongside `Alert`/the Fase 3 alert-rules
tables (never touched by this module): `RecommendedAction` is the
persisted result of `engine/recommendations.py::evaluate_recommendations`
running for one location at one pipeline cycle — never a second source of
risk, only a derived, actionable suggestion.

Deliberately has no execution-status field yet (recomendada/executada/
ignorada) — that's explicitly Fase 6 ("Registro de execução da ação")
scope, not this one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import RiskLevel
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RecommendedAction(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "recommended_actions"

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # engine.recommendations.RecommendationRule.key — which catalog rule
    # produced this row, for dedup (one per location/rule/day) and audit.
    rule_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[RiskLevel] = mapped_column(
        SqlEnum(RiskLevel, name="risk_level", native_enum=True, create_type=False),
        nullable=False,
    )
    # The Alert that originated/accompanies this recommendation, when one
    # exists for the same location/day (e.g. a frost-warning Alert already
    # fired) — SET NULL, not CASCADE, so deleting the Alert never erases
    # this recommendation's own record. Never required for a rule to fire.
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # JSON-serialized engine.alert_rules.MetricSnapshot at the moment this
    # was generated — same opaque-text pattern as AlertEvent.snapshot_json,
    # for auditability without a second normalized table.
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
