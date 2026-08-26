"""API keys for third-party/programmatic access (item 1, ADR-0062).

The raw key is never stored — only its SHA-256 hash (`key_hash`), same
principle as `hashed_password`. `key_prefix` is a short, non-secret slice
of the raw key (e.g. ``sp_live_ab12``) kept so a user can tell their own
keys apart in a list without the full secret ever being retrievable again
after creation — standard API-key UX (Stripe/GitHub-style).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL = active. Never deleted outright (an audit trail of what a key
    # once had access to matters even after revocation), only marked.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
