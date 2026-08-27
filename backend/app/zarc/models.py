"""ZARC (Zoneamento Agrícola de Risco Climático) planting-window reference
data — item ZARC, ADR-0069.

Global, not tenant-scoped: a município's official planting window is
government reference data, shared across every tenant, same reasoning as
``app.weather.models.WeatherSource``.
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ZarcRiskWindow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per (município, cultura, ciclo de cultivar, tipo de solo) —
    exactly the MAPA "Tábua de Risco" CSV's own grain, ingested as-is (see
    ``workers/zarc_pipeline.py`` for the field-by-field mapping, backed by
    MAPA's own published data dictionary).

    ``decendios`` holds all 36 ten-day periods of the year in order —
    ``0`` means that period isn't a recommended planting window; a
    non-zero value is the official risk percentage tier for that window
    (20/30/40 — lower is safer), never re-derived or guessed here.
    """

    __tablename__ = "zarc_risk_windows"
    __table_args__ = (Index("ix_zarc_lookup", "geocodigo", "cultura", "cod_solo"),)

    geocodigo: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    uf: Mapped[str] = mapped_column(String(2), nullable=False)
    municipio: Mapped[str] = mapped_column(String(120), nullable=False)
    # ZARC culture names are specific variants, not a generic crop name —
    # e.g. "Milho 1ª Safra" vs "Milho 2ª Safra" vs "Milho Irrigado" are
    # three separate rows here, matched loosely against a talhão's
    # free-text `crop` (see app/locations/zarc_service.py).
    cultura: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cod_ciclo: Mapped[int] = mapped_column(Integer, nullable=False)
    cod_solo: Mapped[int] = mapped_column(Integer, nullable=False)
    safra_ini: Mapped[int] = mapped_column(Integer, nullable=False)
    safra_fin: Mapped[int] = mapped_column(Integer, nullable=False)
    portaria: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decendios: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
