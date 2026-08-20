"""add users.google_sub

Revision ID: 5e36b6016c06
Revises: 0001_bootstrap
Create Date: 2026-08-19 19:14:22.311402

Hand-trimmed: autogenerate also picked up PostGIS's own "tiger geocoder"
tables (addr, county, edges, ...) as "removed" because they aren't part of
our SQLAlchemy metadata — that's Postgres/PostGIS-installed schema noise,
not something this migration should touch.

Guarded with existence checks: ``0001_bootstrap`` calls
``Base.metadata.create_all()`` against the *live* (current) ORM models
rather than a frozen FASE-2 snapshot — so on a brand-new database, bootstrap
already creates ``users.google_sub`` (since the model has had it since FASE
15), and this migration's unconditional ``op.add_column`` would fail with
``DuplicateColumn``. Confirmed broken this way in CI (fresh Postgres every
run) while local dev never noticed, since that DB was bootstrapped before
``google_sub`` existed on the model and has only ever applied migrations
incrementally since. See ADR-0012.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "5e36b6016c06"
down_revision: str | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "google_sub" not in {c["name"] for c in inspector.get_columns("users")}:
        op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    if "ix_users_google_sub" not in {i["name"] for i in inspector.get_indexes("users")}:
        op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "google_sub")
