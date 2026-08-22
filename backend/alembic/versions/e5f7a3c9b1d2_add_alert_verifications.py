"""add alert_verifications

Revision ID: e5f7a3c9b1d2
Revises: d4f8b2e6c9a3
Create Date: 2026-08-22

Hardening ADR-0036 — ground-truth recording infrastructure for the
validation pipeline (``engine/validation.py``). New table, not present in
the frozen baseline (``0001_bootstrap_schema.py``/ADR-0031), so — unlike
several older migrations in this project — no existence guard is needed
here: this migration is the only place `alert_verifications` is ever
created, on every database (fresh or already at head).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a3c9b1d2"
down_revision: str | None = "d4f8b2e6c9a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=True),
        sa.Column("actual_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("alert_id", name="uq_alert_verifications_alert_id"),
    )
    op.create_index(
        op.f("ix_alert_verifications_tenant_id"),
        "alert_verifications",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("alert_verifications")
