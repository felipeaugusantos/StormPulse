"""Forecast/observation pairs per model, per talhão (Fase 2 — Comparação e
Validação de Previsões).

One row per (location, provider, model, target_date, horizon_hours) —
``horizon_hours`` is bucketed to a small fixed set (``HORIZON_BUCKETS_HOURS``,
``app/forecast_comparison/service.py``) rather than the exact hour gap at
collection time, so "MAE at the 3-day horizon" means the same bucket across
every row instead of an arbitrary continuum nobody could aggregate. The
predicted columns are written by the daily snapshot job; the observed
columns start ``NULL`` and are filled in days later by a separate job once
``target_date`` has actually happened — a row with ``observed_at IS NULL``
is simply not usable in any metric yet, never treated as "observed zero".
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ForecastSnapshot(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "forecast_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "provider",
            "model",
            "target_date",
            "horizon_hours",
            name="uq_forecast_snapshot_location_provider_model_date_horizon",
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "Open-Meteo" today (app.weather.open_meteo._PROVIDER_NAME) — kept
    # separate from `model` since a future provider could offer the same
    # model name under a different upstream (unlikely today, but the two
    # concepts are genuinely different and the schema shouldn't conflate
    # them just because there's only one provider right now).
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    # "ecmwf_ifs025" | "gfs_seamless" | "icon_seamless" (Open-Meteo model
    # identifiers) — free text, not an enum: new models appear on the
    # provider's side without a code change here.
    model: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    temperature_max_predicted_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_predicted_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_probability_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gusts_predicted_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)

    # NULL until the day-after job (app.forecast_comparison.service) fills
    # these in from the real observation source — see module docstring.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temperature_max_observed_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    precipitation_observed_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gusts_observed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
