"""add webhook/whatsapp/sms to notification_channel, custom_rule to
alert_event_type (Fase 3 — Alertas Personalizados, ADR-0086)

Revision ID: 67c40c366af6
Revises: 08c0fdcd06e8
Create Date: 2026-09-05 21:00:00.000000

Same pattern as e7f1a3c5b9d2 (OFFICIAL_WARNING) — Postgres native enum
types don't auto-update when the Python StrEnum gains new members, and a
new value can't be used in the same transaction it's added in, so this
stays its own migration ahead of the one that creates tables using it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "67c40c366af6"
down_revision: str | None = "08c0fdcd06e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_channel ADD VALUE IF NOT EXISTS 'WEBHOOK'")
    op.execute("ALTER TYPE notification_channel ADD VALUE IF NOT EXISTS 'WHATSAPP'")
    op.execute("ALTER TYPE notification_channel ADD VALUE IF NOT EXISTS 'SMS'")
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'CUSTOM_RULE'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; a real downgrade would require
    # rebuilding both types from scratch. Not attempted here.
    pass
