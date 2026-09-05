"""Helpers for the `app.tenant_id` / `app.bypass_rls` session GUCs that
row-level security policies (migration ``0b7b9a5dbd11``) key off of.

``SET LOCAL`` (and ``set_config(..., true)``) are transaction-scoped —
they reset the instant a transaction commits or rolls back. Any session
that commits mid-request/mid-cycle and then keeps querying tenant-scoped
tables in the *same* session must re-apply one of these right after that
commit, or the next query runs with no GUC set and RLS fails it closed
(zero rows) regardless of the query's own ``WHERE`` clause — confirmed
live against a real Postgres (``session.refresh()`` right after a commit
was the first case that surfaced this).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings

logger = logging.getLogger(__name__)


class RlsSafetyError(RuntimeError):
    """The connected DB role/table setup doesn't actually give RLS the
    protection migration ``0b7b9a5dbd11`` is meant to provide."""


# Mirror of `_TENANT_SCOPED_TABLES` in that migration — kept as a separate
# literal (not imported) since a startup check shouldn't depend on Alembic
# migration modules being importable/available in every environment that
# runs `create_app()`.
_TENANT_SCOPED_TABLES = (
    "users",
    "locations",
    "alerts",
    "alert_verifications",
    "ndvi_readings",
    "ndvi_images",
    "deforestation_checks",
    "notifications",
    "push_subscriptions",
    "user_reports",
    "storm_risks",
    "api_keys",
    "forecast_snapshots",
)


async def verify_rls_safety(engine: AsyncEngine, settings: Settings) -> None:
    """Confirm the role this process actually connected as can't silently
    defeat RLS, and that every tenant-scoped table still has it on.

    Hard-fails (raises `RlsSafetyError`) in production — this runs once at
    startup, so a bad config never serves a single request. Everywhere
    else it only logs a warning: local/CI conveniences (a superuser DB,
    skipping the RLS migration entirely for a fast unit-test setup) are
    legitimate outside production and shouldn't block them from starting.
    """
    async with engine.connect() as conn:
        role_row = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
        current_role, is_superuser, bypasses_rls = role_row

        problems: list[str] = []
        if is_superuser:
            problems.append(f"runtime role {current_role!r} is a Postgres superuser")
        if bypasses_rls:
            problems.append(f"runtime role {current_role!r} has the BYPASSRLS attribute")
        if current_role == settings.postgres_user:
            problems.append(
                f"runtime role {current_role!r} is the same as the migration/superuser role "
                f"({settings.postgres_user!r}) — they must be different roles"
            )

        table_list = ",".join(f"'{name}'" for name in _TENANT_SCOPED_TABLES)
        unprotected = (
            (
                await conn.execute(
                    text(
                        f"SELECT relname FROM pg_class "
                        f"WHERE relname IN ({table_list}) "
                        f"AND (NOT relrowsecurity OR NOT relforcerowsecurity)"
                    )
                )
            )
            .scalars()
            .all()
        )
        if unprotected:
            problems.append(
                "tables missing ENABLE+FORCE ROW LEVEL SECURITY: "
                f"{sorted(unprotected)} (has migration 0b7b9a5dbd11 run?)"
            )

    if not problems:
        return
    message = "RLS safety check failed: " + "; ".join(problems)
    if settings.environment == "production":
        raise RlsSafetyError(message)
    logger.warning(message)


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope subsequent queries in this transaction to one tenant.

    A regular function call (`set_config`), not the `SET LOCAL` statement
    — Postgres's `SET`/`SET LOCAL` grammar doesn't accept bind parameters
    at all (confirmed live: raises a syntax error), so this is the only
    way to pass `tenant_id` as an actual query parameter rather than
    string-interpolating it into SQL text.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


async def bypass_rls(session: AsyncSession) -> None:
    """Cross-tenant escape hatch for the request's remaining queries —
    only ever called from the three narrow, audited call sites documented
    in migration ``0b7b9a5dbd11``: the JWT self-lookup in
    ``get_current_user``, ``require_platform_admin``, and workers'
    ``session_scope()``. No bind parameter needed (a fixed literal), so
    this can use `SET LOCAL` directly.
    """
    await session.execute(text("SET LOCAL app.bypass_rls = 'on'"))
