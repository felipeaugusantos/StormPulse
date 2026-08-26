"""add official_warning to alert_event_type enum

Revision ID: e7f1a3c5b9d2
Revises: d4b8e2f6a9c1
Create Date: 2026-08-26 19:20:00.000000

Same pattern as c9e2f6a1d4b8 (agro alert event types) — Postgres native
enum types don't auto-update when the Python StrEnum gains new members.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e7f1a3c5b9d2"
down_revision: str | None = "d4b8e2f6a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'OFFICIAL_WARNING'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; a real downgrade would require
    # rebuilding alert_event_type from scratch. Not attempted here.
    pass
