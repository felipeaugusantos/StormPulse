"""NDVI-per-talhão pipeline (FASE 29, ADR-0053).

Only ever looks at talhões — locations with `parent_location_id` set (a
plot inside a farm) *and* a drawn `boundary_geojson` (FASE 27) — a
farm-level point has no polygon to compute a vegetation index over. Off by
default (`settings.ndvi_enabled=False`); when a misconfigured account has
`ndvi_enabled=true` without credentials, `Settings` itself refuses to boot
(see `app/core/config.py`'s validator) rather than silently falling back to
mock data here.

One talhão's provider failure (cloud cover, API hiccup) never aborts the
whole cycle — every other talhão still gets its own attempt.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.locations.models import Location
from app.ndvi.factory import get_ndvi_provider
from app.ndvi.models import NdviReading
from app.ndvi.provider import NdviProvider, NdviProviderUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class NdviCycleSummary:
    enabled: bool
    talhoes_checked: int = 0
    readings_created: int = 0
    failures: int = 0


def _eligible_talhoes(session: Session) -> list[Location]:
    stmt = select(Location).where(
        Location.is_active.is_(True),
        Location.parent_location_id.is_not(None),
        Location.boundary_geojson.is_not(None),
    )
    return list(session.scalars(stmt))


async def _run_all_talhoes(
    session: Session, talhoes: list[Location], provider: NdviProvider, settings: Settings
) -> tuple[int, int]:
    created = 0
    failed = 0
    for talhao in talhoes:
        assert talhao.boundary_geojson is not None  # guaranteed by _eligible_talhoes's filter
        try:
            observation = await provider.get_ndvi(
                talhao.boundary_geojson, lookback_days=settings.ndvi_lookback_days
            )
        except NdviProviderUnavailableError as exc:
            logger.warning(
                "NDVI unavailable for talhão",
                extra={"location_id": str(talhao.id), "error": str(exc)},
            )
            failed += 1
            continue
        session.add(
            NdviReading(
                tenant_id=talhao.tenant_id,
                location_id=talhao.id,
                observed_at=observation.observed_at,
                ndvi_mean=observation.ndvi_mean,
                valid_pixel_percent=observation.valid_pixel_percent,
                is_mock=observation.provenance.is_mock,
            )
        )
        created += 1
    return created, failed


def run_ndvi_pipeline_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: NdviProvider | None = None,
) -> NdviCycleSummary:
    settings = settings or get_settings()
    if not settings.ndvi_enabled:
        return NdviCycleSummary(enabled=False)

    provider = provider or get_ndvi_provider(settings)
    talhoes = _eligible_talhoes(session)

    async def _run() -> tuple[int, int]:
        assert provider is not None
        try:
            return await _run_all_talhoes(session, talhoes, provider, settings)
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()

    created, failed = asyncio.run(_run())
    session.flush()

    return NdviCycleSummary(
        enabled=True,
        talhoes_checked=len(talhoes),
        readings_created=created,
        failures=failed,
    )
