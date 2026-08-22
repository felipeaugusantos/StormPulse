"""AlertVerification — ground-truth outcome recorded against a past Alert.

Infrastructure for the validation pipeline (hardening ADR-0036,
``engine/validation.py``): given an ``Alert`` StormPulse already emitted,
records whether the predicted event was later actually confirmed, by whom,
and (for storm-approach alerts) when it actually arrived vs. the ETA that
was predicted at the time.

Deliberately has **no** public API endpoint yet — recording ground truth
today means someone (a developer, an operator) writing a row directly,
because no verified external observation source (real radar, a working
crowdsourced-report flow) is wired up to populate it automatically or
safely from untrusted input. Adding a public "confirm this alert" endpoint
is real product surface — explicitly out of scope for this hardening
cycle (see ADR-0036 for the full reasoning) and left for a future,
separately-considered feature phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AlertVerification(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "alert_verifications"

    # `unique=True` alone already gives Postgres a unique index on this
    # column — no separate `index=True` needed on top of it.
    alert_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Whether the predicted event was actually confirmed to have happened —
    # `None` means "recorded but not yet resolved" (e.g. still waiting to
    # see if the storm arrives), distinct from a real False outcome.
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # When the predicted event actually happened, if it did — compared
    # against the Alert's own predicted ETA (`engine.validation.EtaSample`)
    # to compute ETA error. Null when there was no ETA to verify (e.g. a
    # STORM_DETECTED alert has no arrival prediction) or the event never
    # happened at all.
    actual_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Free-text context — e.g. "confirmed via Defesa Civil bulletin",
    # "no rain observed at the location, false positive". Never treated as
    # user-facing content, purely an internal audit trail.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional confidence in this verification itself (0-1) — a verification
    # from an official bulletin is more trustworthy than an unconfirmed
    # crowdsourced note, once that path exists.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
