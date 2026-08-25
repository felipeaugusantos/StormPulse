"""Audit trail for platform-admin actions (FASE 28 Fase 2, ADR-0049).

Global, not tenant-scoped — a single operator's actions can span every
tenant in the base. Actor/target emails are denormalized (kept even if the
account is later deleted) precisely because this is a record of what
happened, which must survive the accounts involved.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.encrypted_types import EncryptedString
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AdminAuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_audit_log"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Encrypted at rest (ADR-0055) — never queried by value (only ever
    # listed/ordered by created_at), so no blind-index column needed here,
    # unlike users.email/google_sub.
    actor_email: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_email: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
