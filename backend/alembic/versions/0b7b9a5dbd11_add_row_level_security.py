"""add row-level security policies for tenant-scoped tables

Revision ID: 0b7b9a5dbd11
Revises: 817b1b97cac3
Create Date: 2026-08-25 15:00:00.000000

Second, database-level layer for tenant isolation. Until now, isolation
was purely application-level — every query already filters by tenant_id
correctly (audited throughout this project) — but with no trap if a
*future* query ever forgets to. RLS makes a missing filter fail closed
(zero rows returned) instead of silently leaking another tenant's data.

**A real, live-tested finding drove this design.** The obvious approach —
just add policies, keep the single existing ``stormpulse`` DB role for
everything — was tried against a real Postgres container before writing
any of this, and does *not* work: Docker's ``POSTGRES_USER`` bootstrap
role is created a Postgres **superuser**, and superusers unconditionally
bypass row-level security regardless of ``FORCE ROW LEVEL SECURITY``.
Postgres also refuses to let that bootstrap role strip its own superuser
bit (``ALTER ROLE ... NOSUPERUSER`` errors: "The bootstrap user must have
the SUPERUSER attribute"). So this migration creates a **second,
ordinary (non-superuser) role**, ``stormpulse_app`` — granted only DML on
every table, nothing else — which becomes the identity the live API and
Celery workers actually connect as from here on (see
``app/core/config.py``'s ``database_url``/``sync_database_url`` vs the
new ``migration_database_url``, which keeps using the superuser for
Alembic only). Verified end-to-end against a throwaway Postgres
container: zero rows with no tenant GUC set, correct tenant-only rows
once scoped, cross-tenant INSERT correctly rejected by ``WITH CHECK``.

**Three legitimate cross-tenant access patterns** exist even for the new
restricted role and would otherwise break under strict enforcement:

1. ``app/api/deps.py``'s ``get_current_user`` — the very first query of
   every authenticated request looks up the caller's own row by the id
   inside their signed JWT, *before* their tenant is known (that's what
   the lookup is for). Bypass is set for that one lookup only, then
   immediately replaced with the real ``app.tenant_id`` for the rest of
   the request.
2. ``app/api/deps.py``'s ``require_platform_admin`` — once the Python-level
   ``is_platform_admin`` check on the caller's *own* (already
   tenant-scoped) row has passed, the admin panel's entire purpose is
   cross-tenant visibility (FASE 28, ADR-0048), so bypass stays on for
   the rest of that request.
3. ``workers/db.py``'s ``session_scope()`` — every Celery pipeline cycle
   processes every tenant's locations/alerts/notifications in one
   transaction by design (never driven by end-user request input), so
   workers bypass unconditionally for their whole session.

All three set the same narrow, explicit session-local escape hatch,
``app.bypass_rls = 'on'`` — never a blanket role-level ``BYPASSRLS``,
which would silently defeat RLS for *any* query on that connection,
including ones nobody has audited yet. Everywhere else, an unset
``app.tenant_id`` (``current_setting(..., true)`` returns ``NULL``) fails
closed.

Table/role names interpolated into the DDL below come only from hardcoded
constants in this file — never user input. The app-role password comes
from this deployment's own ``Settings`` (``POSTGRES_APP_PASSWORD``), with
single quotes doubled for safe embedding as a string literal — neither
``SET LOCAL`` nor ``ALTER ROLE ... PASSWORD`` accept bind parameters in
Postgres (confirmed live; that's a hard grammar restriction on these
utility statements, not a driver limitation), so this is the standard way
to embed a literal value in DDL, same technique Postgres itself uses.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.config import POSTGRES_APP_ROLE, get_settings

revision: str = "0b7b9a5dbd11"
down_revision: str | None = "817b1b97cac3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Hardening follow-up: this used to be its own literal ("stormpulse_app")
# instead of importing the shared constant — `Settings.postgres_app_user`
# was a *configurable* field back then that this migration never actually
# read, so setting POSTGRES_APP_USER to anything else silently broke the
# deploy (the app would connect as a role this migration never created).
# Importing the constant here is a pure refactor, not a behavior change —
# the value is identical ("stormpulse_app"), verified by re-running this
# migration from scratch against a disposable Postgres and diffing the
# resulting role/grants against the pre-refactor version. Never change
# this migration's actual DDL logic; it's already applied in production.
_APP_ROLE = POSTGRES_APP_ROLE

# Every table with a `tenant_id` column (via `TenantMixin`) — verified
# against `app/**/models.py` at the time this migration was written.
# Deliberately excludes global/shared tables that have no tenant_id at
# all: tenants (the parent), storm_cells/storm_tracks/storm_observations,
# convective_watches, satellite_images, lightning_strikes, weather_sources,
# radar_frames, admin_audit_log (explicitly cross-tenant by design).
_TENANT_SCOPED_TABLES = (
    "users",
    "locations",
    "alerts",
    "alert_verifications",
    "ndvi_readings",
    "notifications",
    "push_subscriptions",
    "user_reports",
    "storm_risks",
)

_CREATE_POLICY_SQL = """
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


def upgrade() -> None:
    settings = get_settings()
    escaped_password = settings.postgres_app_password.replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                CREATE ROLE {_APP_ROLE} LOGIN;
            END IF;
        END $$;
        """
    )
    # Password is set unconditionally (not just on first creation) so that
    # rotating POSTGRES_APP_PASSWORD and re-running migrations — a no-op
    # for the role's existence — still picks up the new value.
    op.execute(f"ALTER ROLE {_APP_ROLE} WITH PASSWORD '{escaped_password}'")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    # So tables created by *future* migrations (still run as the superuser)
    # are automatically visible to the app role too, without editing this
    # migration again.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {_APP_ROLE}"
    )

    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_CREATE_POLICY_SQL.format(table=table))


def downgrade() -> None:
    for table in _TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    # The role itself is left in place on downgrade — dropping it would
    # also need every GRANT/default-privilege reverted first, and the app
    # would need to stop using it *before* the drop or every subsequent
    # connection fails. Not worth the risk for a downgrade path; a role
    # with no RLS policies protecting it is no worse than the pre-migration
    # state.
