"""add multi-index vegetation history, quality and dated maps

Revision ID: f5a7e2c9d1b4
Revises: 08c0fdcd06e8
Create Date: 2026-09-05 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "f5a7e2c9d1b4"
down_revision: str | None = "08c0fdcd06e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_column_if_missing(table: str, column: sa.Column[object]) -> None:
    columns = {item["name"] for item in inspect(op.get_bind()).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def upgrade() -> None:
    # PostgreSQL native enums need the new alert value before ORM inserts can use it.
    op.execute(
        "ALTER TYPE alert_event_type ADD VALUE IF NOT EXISTS "
        "'VEGETATION_INDEX_DROP' AFTER 'OFFICIAL_WARNING'"
    )

    for table in ("ndvi_readings", "ndvi_images"):
        _add_column_if_missing(
            table, sa.Column("index_name", sa.String(8), nullable=False, server_default="ndvi")
        )
        _add_column_if_missing(
            table,
            sa.Column("source_name", sa.String(120), nullable=False, server_default="unknown"),
        )
        _add_column_if_missing(
            table,
            sa.Column("cloud_cover_percent", sa.Float(), nullable=False, server_default="0"),
        )
        _add_column_if_missing(
            table, sa.Column("quality", sa.String(12), nullable=False, server_default="high")
        )
        _add_column_if_missing(
            table, sa.Column("reliable", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    _add_column_if_missing(
        "ndvi_readings",
        sa.Column("vigor_zones_json", sa.Text(), nullable=False, server_default="[]"),
    )

    constraints = {
        item["name"] for item in inspect(op.get_bind()).get_unique_constraints("ndvi_images")
    }
    if "uq_ndvi_image_location" in constraints:
        op.drop_constraint("uq_ndvi_image_location", "ndvi_images", type_="unique")
    if "uq_vegetation_image_acquisition" not in constraints:
        op.create_unique_constraint(
            "uq_vegetation_image_acquisition",
            "ndvi_images",
            ["location_id", "index_name", "observed_at"],
        )
    op.create_index(
        "ix_ndvi_readings_location_index_observed",
        "ndvi_readings",
        ["location_id", "index_name", "observed_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_ndvi_images_location_index_observed",
        "ndvi_images",
        ["location_id", "index_name", "observed_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ndvi_images_location_index_observed", table_name="ndvi_images")
    op.drop_index("ix_ndvi_readings_location_index_observed", table_name="ndvi_readings")
    op.drop_constraint("uq_vegetation_image_acquisition", "ndvi_images", type_="unique")
    # Keep only the newest map per plot so restoring the old constraint is safe.
    op.execute(
        """DELETE FROM ndvi_images AS old USING ndvi_images AS newer
        WHERE old.location_id = newer.location_id
          AND (old.observed_at < newer.observed_at
               OR (old.observed_at = newer.observed_at AND old.id::text < newer.id::text))"""
    )
    op.create_unique_constraint("uq_ndvi_image_location", "ndvi_images", ["location_id"])
    for name in ("reliable", "quality", "cloud_cover_percent", "source_name", "index_name"):
        op.drop_column("ndvi_images", name)
    for name in (
        "vigor_zones_json",
        "reliable",
        "quality",
        "cloud_cover_percent",
        "source_name",
        "index_name",
    ):
        op.drop_column("ndvi_readings", name)
    # PostgreSQL enum values are intentionally not removed in downgrade.
