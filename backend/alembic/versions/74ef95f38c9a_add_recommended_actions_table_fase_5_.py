"""add recommended_actions table (Fase 5 — Motor de recomendação, ADR-0089)

Revision ID: 74ef95f38c9a
Revises: 091a6d2694e6
Create Date: 2026-09-07 16:37:46.731450

One tenant-scoped table, additive alongside Alert/the Fase 3 alert-rules
tables (untouched) — see app/recommendations/models.py module docstring.
Same RLS ENABLE/FORCE/CREATE POLICY sequence as every tenant-scoped table
added since ``0b7b9a5dbd11`` (project rule: never create one without RLS
from the start). No new GRANT needed — that migration already set ALTER
DEFAULT PRIVILEGES. The table name is a fixed literal, never external
input — same "nosec: hardcoded" pattern as ``7e8060f3f148``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "74ef95f38c9a"
down_revision: str | None = "091a6d2694e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recommended_actions"


def _policy_sql() -> str:
    # nosec: `_TABLE` is a fixed literal, never external input.
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = '{_TABLE}' AND policyname = 'tenant_isolation'
    ) THEN
        EXECUTE 'CREATE POLICY tenant_isolation ON {_TABLE}
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if _TABLE not in existing:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "location_id",
                sa.Uuid(),
                sa.ForeignKey("locations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("rule_key", sa.String(length=60), nullable=False, index=True),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("level", PGEnum(name="risk_level", create_type=False), nullable=False),
            sa.Column(
                "alert_id",
                sa.Uuid(),
                sa.ForeignKey("alerts.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_policy_sql())


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(_TABLE)
