"""bootstrap schema: enable PostGIS and create initial tables

Hardening ADR-0031 (FASE-hardening 6): this migration used to call
``Base.metadata.create_all()`` against the *current* ORM models — meaning
a brand-new database always got whatever columns the models happen to
have *today*, not what they had when each later migration was written.
Every column added since (``parent_location_id``, ``crop``,
``boundary_geojson``, ``color``, Expo push support, ...) would silently
already exist by the time its own migration ran, hidden only by that
migration's own ``if not exists`` guard. The history was real (every
migration really did get authored and reviewed at that point in time),
but it was never actually *exercised* end-to-end on a fresh database —
the baseline always raced ahead of it.

This migration now applies a **frozen DDL snapshot** (``sql/0001_baseline_schema.sql``,
generated via ``pg_dump --schema-only`` against a database that had run
every migration through ``d4f8b2e6c9a3`` — the tip as of this ADR) instead
of importing live models. A fresh database now genuinely walks the full
migration history: this creates the FASE-2-era shape, then each
subsequent migration in the chain actually adds its own column, for
real, in order — exactly like it would have on day one.

**Existing databases already at or past this revision are unaffected** —
Alembic tracks applied revisions in ``alembic_version``; it never re-runs
a migration a database has already recorded as applied. Only a database
that has *never* run any migration (a brand-new one) executes this new
body. See ADR-0031 for the full upgrade/rollback/re-stamping matrix.

Revision ID: 0001_bootstrap
Revises:
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_DIR = Path(__file__).parent / "sql"

# Every table/type this baseline creates — used only by `downgrade()`, to
# drop them explicitly without depending on live ORM metadata (the whole
# point of this ADR is that this migration must never import app.models).
# Fixed, hand-written list — never built from any external/user input.
_TABLES = (
    "alert_preferences",
    "alerts",
    "convective_watches",
    "lightning_strikes",
    "locations",
    "notifications",
    "push_subscriptions",
    "radar_frames",
    "satellite_images",
    "storm_cells",
    "storm_observations",
    "storm_risks",
    "storm_tracks",
    "tenants",
    "user_reports",
    "users",
    "weather_sources",
)

_ENUM_TYPES = (
    "alert_event_type",
    "alert_type",
    "notification_channel",
    "notification_status",
    "report_status",
    "report_type",
    "risk_level",
    "storm_severity",
    "track_trend",
    "user_role",
    "weather_source_kind",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    sql = (_SQL_DIR / "0001_baseline_schema.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    # Table/type names are a fixed tuple defined above in this same file —
    # never user input — so building the DROP statements this way is safe.
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
    for enum_type in _ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS public.{enum_type}")
    # PostGIS extension is intentionally left in place on downgrade.
