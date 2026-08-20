"""add convective_watches and alerts.convective_watch_id

Revision ID: f53125d00c98
Revises: 5e36b6016c06
Create Date: 2026-08-19 20:23:57.057947

Hand-trimmed: autogenerate also picked up PostGIS's own "tiger geocoder"
tables as "removed" (same noise as revision 5e36b6016c06) — not part of our
SQLAlchemy metadata, not something this migration should touch.
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "f53125d00c98"
down_revision: str | None = "5e36b6016c06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "convective_watches",
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column(
            "centroid",
            geoalchemy2.types.Geography(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geography(geometry_type="POLYGON", srid=4326),
            nullable=True,
        ),
        sa.Column("min_brightness_temp_k", sa.Float(), nullable=False),
        sa.Column("area_km2", sa.Float(), nullable=True),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("direction_deg", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("experimental", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
    )
    # No explicit GIST index for centroid/geometry: geoalchemy2 attaches a
    # DDL event to Geography columns that auto-creates the spatial index as
    # a side effect of op.create_table() — an explicit op.create_index()
    # here would duplicate it and fail (confirmed by trial).
    op.create_index(
        op.f("ix_convective_watches_detected_at"),
        "convective_watches",
        ["detected_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_convective_watches_is_active"), "convective_watches", ["is_active"], unique=False
    )
    op.add_column("alerts", sa.Column("convective_watch_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_alerts_convective_watch_id"), "alerts", ["convective_watch_id"], unique=False
    )
    op.create_foreign_key(
        "fk_alerts_convective_watch_id",
        "alerts",
        "convective_watches",
        ["convective_watch_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_alerts_convective_watch_id", "alerts", type_="foreignkey")
    op.drop_index(op.f("ix_alerts_convective_watch_id"), table_name="alerts")
    op.drop_column("alerts", "convective_watch_id")
    op.drop_table("convective_watches")
