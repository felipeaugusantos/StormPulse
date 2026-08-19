"""Synchronous DB session for workers.

Celery tasks are synchronous and CPU/IO-bound in short bursts, so they use a
plain sync engine (psycopg2) rather than the app's async engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)


def rebind(settings: Settings) -> None:
    """Rebind the engine (used by scripts/tests to point at another database)."""
    global _engine
    _engine = create_engine(settings.sync_database_url, pool_pre_ping=True, future=True)
    SessionLocal.configure(bind=_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
