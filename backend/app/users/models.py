"""User model with RBAC role and hashed password."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserRole
from app.db.base import Base
from app.db.encrypted_types import EncryptedString
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Encrypted at rest (AES-256-GCM, ADR-0055) — the ORM attribute still
    # reads/writes plaintext (EncryptedString), so every existing call site
    # is unchanged. Because AES-GCM uses a random nonce per row, the
    # ciphertext itself is never equal across two rows with the same
    # plaintext — `email_index` (deterministic HMAC-SHA256,
    # `app.core.crypto.blind_index`) is the actual uniqueness/lookup key;
    # always keep it in sync when writing `email`.
    email: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    email_index: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stable Google account id ("sub" claim) for Google-only or linked
    # accounts. NULL for accounts that never used Google sign-in. Kept
    # separate from email (which can change) as the link key. Encrypted
    # like `email` above — `google_sub_index` is the real lookup/uniqueness
    # key (nullable, since most accounts never link Google).
    google_sub: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    google_sub_index: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
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
    # Set on every successful password/Google login (FASE 28 Fase 3,
    # ADR-0051) — never on a token refresh, which happens automatically in
    # the background and isn't a deliberate sign-in. NULL for an account
    # that has never logged in since this column existed (a fresh
    # registration, or one that predates this migration). The only reader
    # is the platform-admin "active users" metric — nothing in the app's
    # own auth/authorization logic depends on it.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
