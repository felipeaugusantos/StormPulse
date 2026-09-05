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
import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import (
    AlertEventType,
    NotificationChannel,
    NotificationStatus,
    RiskLevel,
    VegetationIndex,
)
from app.locations.models import Location
from app.ndvi.analytics import HistoricalValue, has_persistent_drop
from app.ndvi.factory import get_ndvi_provider
from app.ndvi.models import NdviImage, NdviReading
from app.ndvi.provider import NdviObservation, NdviProvider, NdviProviderUnavailableError
from app.notifications.models import Notification

logger = logging.getLogger(__name__)


@dataclass
class NdviCycleSummary:
    enabled: bool
    talhoes_checked: int = 0
    readings_created: int = 0
    failures: int = 0
    alerts_created: int = 0


_INDICES = tuple(VegetationIndex)


async def _persist_ndvi_image(
    session: Session,
    talhao: Location,
    observation: NdviObservation,
    provider: NdviProvider,
    settings: Settings,
) -> None:
    """Persist a dated map for side-by-side comparison, deduplicated by acquisition."""
    assert talhao.boundary_geojson is not None  # guaranteed by _eligible_talhoes's filter
    existing = session.scalars(
        select(NdviImage).where(
            NdviImage.location_id == talhao.id,
            NdviImage.index_name == observation.index_name.value,
            NdviImage.observed_at == observation.observed_at,
        )
    ).one_or_none()
    if existing is not None:
        return
    try:
        png = await provider.get_index_image(
            talhao.boundary_geojson,
            index_name=observation.index_name,
            observed_at=observation.observed_at,
        )
    except NdviProviderUnavailableError as exc:
        logger.warning(
            "vegetation-index image unavailable for talhão",
            extra={
                "location_id": str(talhao.id),
                "index_name": observation.index_name.value,
                "error": str(exc),
            },
        )
        return
    session.add(
        NdviImage(
            tenant_id=talhao.tenant_id,
            location_id=talhao.id,
            observed_at=observation.observed_at,
            index_name=observation.index_name.value,
            source_name=observation.provenance.source_name,
            cloud_cover_percent=observation.cloud_cover_percent,
            quality=observation.quality.value,
            reliable=observation.reliable,
            png_data=png,
            is_mock=observation.provenance.is_mock,
        )
    )


def _persist_reading(session: Session, talhao: Location, observation: NdviObservation) -> bool:
    existing = session.scalars(
        select(NdviReading).where(
            NdviReading.location_id == talhao.id,
            NdviReading.index_name == observation.index_name.value,
            NdviReading.observed_at == observation.observed_at,
        )
    ).one_or_none()
    if existing is not None:
        return False
    session.add(
        NdviReading(
            tenant_id=talhao.tenant_id,
            location_id=talhao.id,
            observed_at=observation.observed_at,
            ndvi_mean=observation.ndvi_mean,
            valid_pixel_percent=observation.valid_pixel_percent,
            index_name=observation.index_name.value,
            source_name=observation.provenance.source_name,
            cloud_cover_percent=observation.cloud_cover_percent,
            quality=observation.quality.value,
            reliable=observation.reliable,
            vigor_zones_json=json.dumps([zone.model_dump() for zone in observation.vigor_zones]),
            is_mock=observation.provenance.is_mock,
        )
    )
    return True


def _emit_persistent_drop_alert(
    session: Session, talhao: Location, observation: NdviObservation
) -> bool:
    if observation.provenance.is_mock or not observation.reliable:
        return False
    rows = list(
        session.scalars(
            select(NdviReading)
            .where(
                NdviReading.location_id == talhao.id,
                NdviReading.index_name == observation.index_name.value,
            )
            .order_by(NdviReading.observed_at.asc())
        )
    )
    values = [HistoricalValue(row.ndvi_mean, row.reliable) for row in rows]
    values.append(HistoricalValue(observation.ndvi_mean, observation.reliable))
    if not has_persistent_drop(values):
        return False
    marker = observation.observed_at.date().isoformat()
    dedup_key = f"{talhao.id}:{observation.index_name.value}:{marker}:vegetation_drop"
    if session.scalars(
        select(Alert).where(Alert.tenant_id == talhao.tenant_id, Alert.dedup_key == dedup_key)
    ).first():
        return False
    label = observation.index_name.value.upper()
    alert = Alert(
        tenant_id=talhao.tenant_id,
        user_id=talhao.user_id,
        location_id=talhao.id,
        event_type=AlertEventType.VEGETATION_INDEX_DROP,
        level=RiskLevel.ORANGE,
        title=f"Queda persistente de {label} em {talhao.name}",
        message=(
            f"O {label} caiu em três aquisições confiáveis consecutivas. "
            "Verifique o talhão; nuvens e imagens de baixa qualidade foram excluídas da análise."
        ),
        dedup_key=dedup_key,
    )
    session.add(alert)
    session.flush()
    session.add(
        Notification(
            tenant_id=talhao.tenant_id,
            alert_id=alert.id,
            user_id=talhao.user_id,
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
        )
    )
    return True


def _eligible_talhoes(session: Session) -> list[Location]:
    stmt = select(Location).where(
        Location.is_active.is_(True),
        Location.parent_location_id.is_not(None),
        Location.boundary_geojson.is_not(None),
    )
    return list(session.scalars(stmt))


async def _run_all_talhoes(
    session: Session, talhoes: list[Location], provider: NdviProvider, settings: Settings
) -> tuple[int, int, int]:
    created = 0
    failed = 0
    alerts = 0
    for talhao in talhoes:
        assert talhao.boundary_geojson is not None  # guaranteed by _eligible_talhoes's filter
        try:
            observations = await provider.get_index_history(
                talhao.boundary_geojson,
                indices=_INDICES,
                lookback_days=settings.ndvi_history_lookback_days,
            )
        except NdviProviderUnavailableError as exc:
            logger.warning(
                "NDVI unavailable for talhão",
                extra={"location_id": str(talhao.id), "error": str(exc)},
            )
            failed += 1
            continue
        if not observations:
            failed += 1
            continue
        observations_by_index: dict[VegetationIndex, list[NdviObservation]] = {}
        for observation in sorted(observations, key=lambda item: item.observed_at):
            is_new = (
                session.scalars(
                    select(NdviReading).where(
                        NdviReading.location_id == talhao.id,
                        NdviReading.index_name == observation.index_name.value,
                        NdviReading.observed_at == observation.observed_at,
                    )
                ).one_or_none()
                is None
            )
            if is_new and _emit_persistent_drop_alert(session, talhao, observation):
                alerts += 1
            if _persist_reading(session, talhao, observation):
                created += 1
            observations_by_index.setdefault(observation.index_name, []).append(observation)
        for index_observations in observations_by_index.values():
            # Keep the current acquisition (even if cloudy, clearly labelled as
            # unreliable) plus the two newest reliable maps needed for immediate
            # side-by-side comparison after the first historical backfill.
            selected = {index_observations[-1].observed_at: index_observations[-1]}
            reliable = [item for item in index_observations if item.reliable]
            selected.update({item.observed_at: item for item in reliable[-2:]})
            for observation in selected.values():
                await _persist_ndvi_image(session, talhao, observation, provider, settings)
    return created, failed, alerts


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

    async def _run() -> tuple[int, int, int]:
        assert provider is not None
        try:
            return await _run_all_talhoes(session, talhoes, provider, settings)
        finally:
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()

    created, failed, alerts = asyncio.run(_run())
    session.flush()

    return NdviCycleSummary(
        enabled=True,
        talhoes_checked=len(talhoes),
        readings_created=created,
        failures=failed,
        alerts_created=alerts,
    )
