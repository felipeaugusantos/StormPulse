"""`verify_rls_safety` (`app/core/rls.py`) — the startup guardrail that's
supposed to hard-fail production if the connected role can silently defeat
row-level security, or a tenant-scoped table lost its RLS protection.

The happy path (no problems) is already exercised indirectly by every other
integration test's app startup — what's missing, and what this file adds,
is the failure paths themselves: they're what the check exists to catch,
so they're the ones that actually need direct coverage. Each scenario
connects as a *real* Postgres role/table state (never mocked) — same
discipline as the rest of this project's RLS testing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.core.rls import RlsSafetyError, verify_rls_safety
from app.db.session import create_engine

pytestmark = pytest.mark.integration


def _asyncpg_url(settings: Settings, *, user: str, password: str) -> str:
    """Same shape as `Settings.database_url`, but for an arbitrary role —
    `verify_rls_safety` needs to see what a *misconfigured* connection
    looks like, which the app's own engine (always `postgres_app_user`)
    never produces."""
    return (
        f"postgresql+asyncpg://{user}:{password}@"
        f"{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@pytest.fixture
async def superuser_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """The actual Postgres bootstrap role (`postgres_user`/`postgres_password`)
    — a real superuser, same one Alembic migrations run as
    (`migration_database_url`). Never used by the live app/workers; only
    here, to prove the check catches it if it ever were."""
    engine = create_async_engine(
        _asyncpg_url(settings, user=settings.postgres_user, password=settings.postgres_password)
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_verify_rls_safety_passes_with_the_real_app_role(settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        await verify_rls_safety(engine, settings)  # must not raise
    finally:
        await engine.dispose()


async def test_verify_rls_safety_raises_in_production_for_a_superuser_role(
    settings: Settings, superuser_engine: AsyncEngine
) -> None:
    prod_settings = settings.model_copy(update={"environment": "production"})
    with pytest.raises(RlsSafetyError, match="superuser"):
        await verify_rls_safety(superuser_engine, prod_settings)


async def test_verify_rls_safety_only_warns_outside_production_for_a_superuser_role(
    settings: Settings,
    superuser_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await verify_rls_safety(superuser_engine, settings)  # environment="test" — must not raise
    assert "superuser" in caplog.text


async def test_verify_rls_safety_raises_when_runtime_role_equals_migration_role(
    settings: Settings, superuser_engine: AsyncEngine
) -> None:
    """The superuser bootstrap role IS `settings.postgres_user` by
    definition, so connecting as it also trips this second, independent
    check — a realistic double-failure (someone pointed `DATABASE_URL` at
    the migration role directly), not an artificial one."""
    prod_settings = settings.model_copy(
        update={"environment": "production", "postgres_user": settings.postgres_user}
    )
    with pytest.raises(RlsSafetyError, match="same as the migration"):
        await verify_rls_safety(superuser_engine, prod_settings)


async def test_verify_rls_safety_raises_for_a_bypassrls_role(settings: Settings) -> None:
    role_name = f"test_bypass_{uuid.uuid4().hex[:8]}"
    admin_engine = create_async_engine(
        _asyncpg_url(settings, user=settings.postgres_user, password=settings.postgres_password)
    )
    try:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f"CREATE ROLE {role_name} LOGIN PASSWORD 'test' BYPASSRLS"))
        bypass_engine = create_async_engine(_asyncpg_url(settings, user=role_name, password="test"))
        try:
            prod_settings = settings.model_copy(update={"environment": "production"})
            with pytest.raises(RlsSafetyError, match="BYPASSRLS"):
                await verify_rls_safety(bypass_engine, prod_settings)
        finally:
            await bypass_engine.dispose()
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f"DROP ROLE IF EXISTS {role_name}"))
        await admin_engine.dispose()


async def test_verify_rls_safety_raises_for_a_tenant_table_missing_rls(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    table_name = f"test_unprotected_{uuid.uuid4().hex[:8]}"
    admin_engine = create_async_engine(
        _asyncpg_url(settings, user=settings.postgres_user, password=settings.postgres_password)
    )
    try:
        async with admin_engine.begin() as conn:
            # No ENABLE/FORCE ROW LEVEL SECURITY at all — exactly the state
            # the check exists to catch (a tenant-scoped table someone
            # forgot to lock down, or a migration that hasn't run yet).
            await conn.execute(text(f"CREATE TABLE {table_name} (id int)"))
        monkeypatch.setattr("app.core.rls._TENANT_SCOPED_TABLES", (table_name,))

        engine = create_engine(settings)
        try:
            prod_settings = settings.model_copy(update={"environment": "production"})
            with pytest.raises(RlsSafetyError, match="missing ENABLE\\+FORCE ROW LEVEL SECURITY"):
                await verify_rls_safety(engine, prod_settings)
        finally:
            await engine.dispose()
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        await admin_engine.dispose()
