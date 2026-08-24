"""Tenant model (SaaS account / organization)."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Module selection, chosen at registration (Tempestade and/or Agro —
    # at least one is required, enforced in RegisterIn). Storm defaults to
    # True (the platform's core product); Agro defaults to False (an
    # opt-in add-on). Existing tenants created before this field keep
    # storm_enabled=True, agro_enabled=False via the migration's server
    # default, matching what they already had access to.
    storm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    agro_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
