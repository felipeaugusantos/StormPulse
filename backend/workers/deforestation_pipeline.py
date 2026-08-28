"""Deforestation-check pipeline (item DETER) — INPE DETER/PRODES per talhão.

Same eligibility rule as NDVI (`workers/ndvi_pipeline.py`): only talhões
(``parent_location_id`` set) with a drawn ``boundary_geojson`` — a
farm-level point has no polygon to intersect against INPE's layers.

Unlike NDVI, a single provider call can partially succeed: DETER-AMZ and
PRODES-Cerrado are independent WFS layers, and (confirmed live during
development) INPE's own backend is occasionally unstable enough that one
or both time out on a given attempt. Each source is persisted
independently — a source that failed this cycle simply leaves its
previous ``DeforestationCheck`` row untouched, it's never overwritten with
"no alerts" just because the request itself didn't complete.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.deforestation.factory import get_deforestation_provider
from app.deforestation.models import DeforestationCheck
from app.deforestation.provider import DeforestationCheckResult, DeforestationProvider
from app.locations.models import Location

logger = logging.getLogger(__name__)


@dataclass
class DeforestationCycleSummary:
    enabled: bool
    talhoes_checked: int = 0
    checks_updated: int = 0
    source_failures: int = 0


def _eligible_talhoes(session: Session) -> list[Location]:
    stmt = select(Location).where(
        Location.is_active.is_(True),
        Location.parent_location_id.is_not(None),
        Location.boundary_geojson.is_not(None),
    )
    return list(session.scalars(stmt))


def _persist_source_result(
    session: Session, talhao: Location, result: DeforestationCheckResult, checked_at: datetime
) -> int:
    """Upserts one row per source that actually succeeded this cycle.
    Sources in ``result.unavailable_sources`` are left alone entirely —
    whatever was stored from their last successful check stays as-is."""
    updated = 0
    for source in result.checked_sources:
        source_alerts = [a for a in result.alerts if a.source == source]
        existing = session.scalars(
            select(DeforestationCheck).where(
                DeforestationCheck.location_id == talhao.id,
                DeforestationCheck.source == source,
            )
        ).one_or_none()
        alerts_json = json.dumps([a.model_dump(mode="json") for a in source_alerts])
        if existing is not None:
            existing.checked_at = checked_at
            existing.alert_count = len(source_alerts)
            existing.alerts_json = alerts_json
        else:
            session.add(
                DeforestationCheck(
                    tenant_id=talhao.tenant_id,
                    location_id=talhao.id,
                    source=source,
                    checked_at=checked_at,
                    alert_count=len(source_alerts),
                    alerts_json=alerts_json,
                )
            )
        updated += 1
    return updated


async def _run_all_talhoes(
    session: Session, talhoes: list[Location], provider: DeforestationProvider, settings: Settings
) -> tuple[int, int]:
    updated = 0
    failures = 0
    now = datetime.now(UTC)
    for talhao in talhoes:
        assert talhao.boundary_geojson is not None  # guaranteed by _eligible_talhoes's filter
        result = await provider.check(
            talhao.boundary_geojson, lookback_years=settings.deforestation_lookback_years
        )
        if result.unavailable_sources:
            logger.warning(
                "Deforestation source(s) unavailable for talhão",
                extra={
                    "location_id": str(talhao.id),
                    "unavailable_sources": result.unavailable_sources,
                },
            )
            failures += len(result.unavailable_sources)
        updated += _persist_source_result(session, talhao, result, now)
    return updated, failures


def run_deforestation_check_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: DeforestationProvider | None = None,
) -> DeforestationCycleSummary:
    settings = settings or get_settings()
    if not settings.deforestation_check_enabled:
        return DeforestationCycleSummary(enabled=False)

    provider = provider or get_deforestation_provider(settings)
    talhoes = _eligible_talhoes(session)

    async def _run() -> tuple[int, int]:
        assert provider is not None
        try:
            return await _run_all_talhoes(session, talhoes, provider, settings)
        finally:
            await provider.aclose()

    updated, failures = asyncio.run(_run())
    session.flush()

    return DeforestationCycleSummary(
        enabled=True,
        talhoes_checked=len(talhoes),
        checks_updated=updated,
        source_failures=failures,
    )
