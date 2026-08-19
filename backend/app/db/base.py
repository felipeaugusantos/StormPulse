"""Declarative base for ORM models.

Concrete models arrive in FASE 2. The base lives here so Alembic and the
session layer can import a single ``Base`` from the start.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all StormPulse ORM models."""
