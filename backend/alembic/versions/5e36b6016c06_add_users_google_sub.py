"""add users.google_sub

Revision ID: 5e36b6016c06
Revises: 0001_bootstrap
Create Date: 2026-08-19 19:14:22.311402

Hand-trimmed: autogenerate also picked up PostGIS's own "tiger geocoder"
tables (addr, county, edges, ...) as "removed" because they aren't part of
our SQLAlchemy metadata — that's Postgres/PostGIS-installed schema noise,
not something this migration should touch.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e36b6016c06"
down_revision: str | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "google_sub")
