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

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
