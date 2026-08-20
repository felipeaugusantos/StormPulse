"""add satellite_watch_detected/dissipated to alert_event_type enum

Revision ID: a1c2e3f4b5d6
Revises: f53125d00c98
Create Date: 2026-08-19 23:58:00.000000

Postgres native enum types don't auto-update when the Python StrEnum gains
new members (autogenerate doesn't detect this either) — needs an explicit
ALTER TYPE. No downgrade: Postgres can't drop enum values without rebuilding
the type (and no data uses these values on a legitimate downgrade path).

Note the labels are the Python enum members' *names* (upper-case,
``SATELLITE_WATCH_DETECTED``), not their ``.value`` — that's what
SQLAlchemy's ``Enum(SomeEnum, ...)`` actually stores by default (confirmed
against the existing rows: ``STORM_DETECTED`` etc., not ``storm_detected``),
which caught us out here — the first version of this migration used the
lower-case ``.value`` and had to be corrected.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: str | None = "f53125d00c98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'SATELLITE_WATCH_DETECTED'")
    op.execute("ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS 'SATELLITE_WATCH_DISSIPATED'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums; a real downgrade would require
    # rebuilding alert_event_type from scratch. Not attempted here.
    pass
