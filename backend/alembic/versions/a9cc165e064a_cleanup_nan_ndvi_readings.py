"""cleanup NaN ndvi_readings

Revision ID: a9cc165e064a
Revises: f2b8d4e6a1c9
Create Date: 2026-08-28 12:50:00.000000

Data cleanup, not a schema change. `ndvi_readings.ndvi_mean` is NOT NULL
and always has been — confirmed live against production's own schema
(2026-08-28). The bug wasn't SQL NULL: `app/ndvi/sentinel_hub.py` could
pass a Sentinel Hub `NaN` statistic straight through — a valid IEEE-754
float the NOT NULL constraint never rejects, but unrepresentable in JSON,
so it silently became `null` in every API response reading it (frontend
crash, ADR follow-up). The provider now skips a NaN mean before ever
constructing a reading (see that module), but the handful of rows already
written with a NaN `ndvi_mean` before the fix need to go.

Note Postgres does not follow IEEE-754 for `float8`'s own `=`/`<>`
operators the way the standard says (`NaN <> NaN` would be `true` there)
— verified live against this project's own database: Postgres treats
`NaN = NaN` as `true` even for plain `=`, so the usual "never equal to
itself" NaN test doesn't work here. A direct literal comparison against
`'NaN'::double precision` does.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a9cc165e064a"
down_revision: str | None = "f2b8d4e6a1c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM ndvi_readings WHERE ndvi_mean = 'NaN'::double precision")


def downgrade() -> None:
    # Deleted rows held a NaN reading — nothing usable to restore.
    pass
