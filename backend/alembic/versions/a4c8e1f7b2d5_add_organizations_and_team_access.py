"""add organizations, invitations and scoped team access

Revision ID: a4c8e1f7b2d5
Revises: f5a7e2c9d1b4
Create Date: 2026-09-05 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a4c8e1f7b2d5"
down_revision: str | None = "f5a7e2c9d1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("organization_invitations", "location_access_grants", "access_audit_logs")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{table}'
                       AND policyname = 'tenant_isolation') THEN
          EXECUTE 'CREATE POLICY tenant_isolation ON {table}
            USING (current_setting(''app.bypass_rls'', true) = ''on''
              OR tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)
            WITH CHECK (current_setting(''app.bypass_rls'', true) = ''on''
              OR tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)';
        END IF; END $$"""
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO stormpulse_app")


def upgrade() -> None:
    for value in ("OWNER", "AGRONOMIST", "VIEWER"):
        op.execute(f"ALTER TYPE user_role ADD VALUE IF NOT EXISTS '{value}'")

    columns = {item["name"] for item in inspect(op.get_bind()).get_columns("users")}
    if "organization_wide_access" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "organization_wide_access", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )
    if "access_expires_at" not in columns:
        op.add_column("users", sa.Column("access_expires_at", sa.DateTime(timezone=True)))

    existing = set(inspect(op.get_bind()).get_table_names())
    if "organization_invitations" not in existing:
        op.create_table(
            "organization_invitations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("email_index", sa.String(64), nullable=False),
            sa.Column("role", sa.String(24), nullable=False),
            sa.Column("location_id", sa.Uuid()),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("access_expires_at", sa.DateTime(timezone=True)),
            sa.Column("accepted_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
            sa.Column("accepted_by_user_id", sa.Uuid()),
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
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
    if "location_access_grants" not in existing:
        op.create_table(
            "location_access_grants",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("location_id", sa.Uuid(), nullable=False),
            sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
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
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "location_id", name="uq_user_location_access"),
        )
    if "access_audit_logs" not in existing:
        op.create_table(
            "access_audit_logs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("actor_user_id", sa.Uuid()),
            sa.Column("target_user_id", sa.Uuid()),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("location_id", sa.Uuid()),
            sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
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
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        )
    indexes = (
        ("ix_organization_invitations_email_index", "organization_invitations", ["email_index"]),
        ("ix_organization_invitations_location_id", "organization_invitations", ["location_id"]),
        ("ix_organization_invitations_token_hash", "organization_invitations", ["token_hash"]),
        ("ix_location_access_grants_user_id", "location_access_grants", ["user_id"]),
        ("ix_location_access_grants_location_id", "location_access_grants", ["location_id"]),
        ("ix_access_audit_logs_actor_user_id", "access_audit_logs", ["actor_user_id"]),
        ("ix_access_audit_logs_target_user_id", "access_audit_logs", ["target_user_id"]),
        ("ix_access_audit_logs_action", "access_audit_logs", ["action"]),
    )
    existing_indexes = {
        index["name"] for table in _TABLES for index in inspect(op.get_bind()).get_indexes(table)
    }
    for name, table, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, table, columns)
    for table in _TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.drop_column("users", "access_expires_at")
    op.drop_column("users", "organization_wide_access")
    # PostgreSQL enum values intentionally remain.
