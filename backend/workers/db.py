"""Synchronous DB session for workers.

Celery tasks are synchronous and CPU/IO-bound in short bursts, so they use a
plain sync engine (psycopg2) rather than the app's async engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401  # register ALL models so FKs resolve in workers
from app.core.config import Settings, get_settings

_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)


def bypass_rls(session: Session) -> None:
    """Re-apply the RLS bypass GUC (see `session_scope` below) — needed
    anywhere a pipeline calls `session.commit()` mid-cycle and then keeps
    touching tenant-scoped tables in the same session: `SET LOCAL` is
    transaction-scoped, so a commit silently ends it (confirmed live:
    `run_ingestion_cycle`'s early `_prune_old_mock_cells` commit was
    doing exactly this, making every location read after it come back
    empty under RLS, with no error — just a quietly-skipped cycle)."""
    session.execute(text("SET LOCAL app.bypass_rls = 'on'"))


def rebind(settings: Settings) -> None:
    """Rebind the engine (used by scripts/tests to point at another database)."""
    global _engine
    _engine = create_engine(settings.sync_database_url, pool_pre_ping=True, future=True)
    SessionLocal.configure(bind=_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Every worker cycle processes every tenant's rows in one transaction
    by design (never driven by end-user request input, unlike the API) —
    RLS's tenant-isolation policies (see the ``0b7b9a5dbd11`` migration)
    would otherwise block that on-purpose cross-tenant sweep, so workers
    bypass unconditionally for their whole session.
    """
    session = SessionLocal()
    try:
        bypass_rls(session)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
