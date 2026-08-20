"""add frost_warning/dry_spell_warning to alert_event_type enum

Revision ID: c9e2f6a1d4b8
Revises: b7d4e1f9a2c3
Create Date: 2026-08-20 15:00:00.000000

Same pattern as a1c2e3f4b5d6 (satellite alert event types): Postgres native
enum types don't auto-update when the Python StrEnum gains new members, and
`ADD VALUE IF NOT EXISTS` makes this safe regardless of whether
0001_bootstrap already created these values on a fresh database (see
ADR-0012) — no existence-check guard needed here, unlike the table/column
migrations.

Labels are the Python enum members' *names* (upper-case), not `.value` —
confirmed against existing rows in a1c2e3f4b5d6.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c9e2f6a1d4b8"
down_revision: str | None = "b7d4e1f9a2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'FROST_WARNING'")
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'DRY_SPELL_WARNING'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; a real downgrade would require
    # rebuilding alert_event_type from scratch. Not attempted here.
    pass
