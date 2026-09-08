"""add field notebook tables (Fase 6 — Caderno de Campo, ADR-0090)

Revision ID: 68d892adfc87
Revises: 74ef95f38c9a
Create Date: 2026-09-07 17:10:00.000000

Four tenant-scoped tables, additive alongside Alert/RecommendedAction
(untouched) — see app/fieldnotes/models.py module docstring for what each
is. Same RLS ENABLE/FORCE/CREATE POLICY sequence as every tenant-scoped
table added since ``0b7b9a5dbd11``. Table names interpolated into the DDL
below all come from the fixed, hardcoded ``_TABLES`` tuple in this file —
never from user/request input — same pattern as ``7e8060f3f148``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "68d892adfc87"
down_revision: str | None = "74ef95f38c9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("field_occurrences", "field_inspections", "field_tasks", "field_photos")


def _policy_sql(table: str) -> str:
    # nosec: `table` is always one of the hardcoded literals in _TABLES.
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = '{table}' AND policyname = 'tenant_isolation'
    ) THEN
        EXECUTE 'CREATE POLICY tenant_isolation ON {table}
            USING (
                current_setting(''app.bypass_rls'', true) = ''on''
                OR tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid
            )
            WITH CHECK (
                current_setting(''app.bypass_rls'', true) = ''on''
                OR tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid
            )';
    END IF;
END $$;
"""


def _enable_rls(table: str) -> None:
    # nosec: `table` is always one of the hardcoded literals in _TABLES.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(_policy_sql(table))


def _disable_rls(table: str) -> None:
    # nosec: `table` is always one of the hardcoded literals in _TABLES.
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _tenant_id_col() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    # SQLAlchemy's `Enum` type persists a Python `StrEnum` member's *name*
    # (e.g. "OPEN"), not its `.value` ("open") — same convention already
    # used by `alert_event_status` (Fase 3). The Postgres enum values here
    # match `FieldOccurrenceStatus`/`FieldTaskStatus`'s member names, not
    # their (lowercase, API-facing) string values.
    occurrence_status = PGEnum("OPEN", "RESOLVED", name="field_occurrence_status")
    occurrence_status.create(bind, checkfirst=True)
    task_status = PGEnum("PENDING", "IN_PROGRESS", "DONE", "CANCELLED", name="field_task_status")
    task_status.create(bind, checkfirst=True)

    if "field_occurrences" not in existing:
        op.create_table(
            "field_occurrences",
            sa.Column("id", sa.Uuid(), primary_key=True),
            _tenant_id_col(),
            sa.Column(
                "location_id",
                sa.Uuid(),
                sa.ForeignKey("locations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "alert_id",
                sa.Uuid(),
                sa.ForeignKey("alerts.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "recommended_action_id",
                sa.Uuid(),
                sa.ForeignKey("recommended_actions.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("category", sa.String(length=60), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column(
                "status",
                PGEnum(name="field_occurrence_status", create_type=False),
                nullable=False,
                server_default="OPEN",
            ),
            sa.Column(
                "reported_by",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            *_timestamps(),
        )

    if "field_inspections" not in existing:
        op.create_table(
            "field_inspections",
            sa.Column("id", sa.Uuid(), primary_key=True),
            _tenant_id_col(),
            sa.Column(
                "location_id",
                sa.Uuid(),
                sa.ForeignKey("locations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "occurrence_id",
                sa.Uuid(),
                sa.ForeignKey("field_occurrences.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column(
                "inspected_by",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            *_timestamps(),
        )

    if "field_tasks" not in existing:
        op.create_table(
            "field_tasks",
            sa.Column("id", sa.Uuid(), primary_key=True),
            _tenant_id_col(),
            sa.Column(
                "location_id",
                sa.Uuid(),
                sa.ForeignKey("locations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "occurrence_id",
                sa.Uuid(),
                sa.ForeignKey("field_occurrences.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "alert_id",
                sa.Uuid(),
                sa.ForeignKey("alerts.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "recommended_action_id",
                sa.Uuid(),
                sa.ForeignKey("recommended_actions.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "assigned_to",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                PGEnum(name="field_task_status", create_type=False),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column(
                "completed_by",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            *_timestamps(),
        )

    if "field_photos" not in existing:
        op.create_table(
            "field_photos",
            sa.Column("id", sa.Uuid(), primary_key=True),
            _tenant_id_col(),
            sa.Column(
                "inspection_id",
                sa.Uuid(),
                sa.ForeignKey("field_inspections.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("object_key", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=100), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "uploaded_by",
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            *_timestamps(),
        )

    for table in _TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        _disable_rls(table)
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.execute("DROP TYPE IF EXISTS field_task_status")
    op.execute("DROP TYPE IF EXISTS field_occurrence_status")
