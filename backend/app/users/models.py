"""User model with RBAC role and hashed password."""

from __future__ import annotations

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserRole
from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stable Google account id ("sub" claim) for Google-only or linked
    # accounts. NULL for accounts that never used Google sign-in. Kept
    # separate from email (which can change) as the link key.
    google_sub: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cross-tenant platform operator flag (FASE 28, ADR-0048) — orthogonal to
    # `role`, which is scoped *within* a tenant. Only a platform admin can
    # see/manage data across every tenant, not just their own. Never settable
    # by a client; only ever flipped by the startup bootstrap in main.py
    # (PLATFORM_ADMIN_EMAIL) or a future dedicated admin action.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
