"""Official meteorological warnings as an alert source (item 3, ADR-0064).

Turns ``WeatherProvider.get_warnings`` (INMET's ``/avisos/ativos`` feed —
the same national, public, no-registration alert source that state/
municipal Civil Defense agencies themselves redistribute) into real
``Alert`` rows for every active monitored ``Location``, on its own
schedule — mirrors ``workers/agro_pipeline.py`` structurally (own decision
logic, not ``AlertEngine``, since a `Warning` has no rain/wind/hail/
lightning score to feed it).

Checked less often than the main storm-ingestion cycle: an official
warning is issued/updated on the order of hours, not minutes, and INMET's
feed is a single shared endpoint per state — no per-location cost beyond
the initial fetch it already pays for elsewhere.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import AlertEventType, NotificationChannel, NotificationStatus, RiskLevel
from app.locations.models import Location
from app.notifications.models import Notification
from app.weather.factory import get_weather_provider
from app.weather.provider import Warning as OfficialWarning
from app.weather.provider import WeatherProvider, WeatherProviderUnavailableError

logger = logging.getLogger(__name__)

_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)

# INMET severities are free-text (ADR-0011) — normalized here to the same
# RiskLevel scale the rest of the alert system already uses. Anything
# unrecognized defaults to yellow rather than silently dropping the
# warning: an unfamiliar severity string is still worth surfacing.
_SEVERITY_TO_RISK_LEVEL: dict[str, RiskLevel] = {
    "perigo potencial": RiskLevel.YELLOW,
    "perigo": RiskLevel.ORANGE,
    "grande perigo": RiskLevel.RED,
}


@dataclass
class OfficialWarningsCycleSummary:
    enabled: bool
    locations_checked: int = 0
    alerts_created: int = 0


def _risk_level_for(severity: str) -> RiskLevel:
    return _SEVERITY_TO_RISK_LEVEL.get(severity.strip().lower(), RiskLevel.YELLOW)


def _dedup_key(location_id: object, warning: OfficialWarning) -> str:
    # Same (kind, severity, description, issued_at) content hashed together
    # — INMET doesn't expose a stable warning ID, so identical content is
    # the only reliable idempotency signal (a re-fetch of the same still-
    # active warning must never re-alert).
    fingerprint = "|".join(
        [warning.kind, warning.severity, warning.description, warning.issued_at.isoformat()]
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    return f"{location_id}:{digest}:{AlertEventType.OFFICIAL_WARNING.value}"


async def _check_location(session: Session, location: Location, provider: WeatherProvider) -> int:
    try:
        warnings = await provider.get_warnings(location.latitude, location.longitude)
    except _RECOVERABLE as exc:
        logger.warning("official warnings unavailable for location %s (%s)", location.id, exc)
        return 0

    created = 0
    for warning in warnings:
        dedup_key = _dedup_key(location.id, warning)
        already = session.scalars(
            select(Alert).where(Alert.tenant_id == location.tenant_id, Alert.dedup_key == dedup_key)
        ).first()
        if already is not None:
            continue

        alert = Alert(
            tenant_id=location.tenant_id,
            user_id=location.user_id,
            location_id=location.id,
            event_type=AlertEventType.OFFICIAL_WARNING,
            level=_risk_level_for(warning.severity),
            title=f"Aviso oficial ({warning.provenance.source_name}) — {location.name}",
            message=warning.description,
            dedup_key=dedup_key,
        )
        session.add(alert)
        session.flush()
        session.add(
            Notification(
                tenant_id=location.tenant_id,
                alert_id=alert.id,
                user_id=location.user_id,
                channel=NotificationChannel.PUSH,
                status=NotificationStatus.PENDING,
            )
        )
        created += 1
    return created


async def _run_all_locations(
    session: Session, locations: list[Location], provider: WeatherProvider
) -> int:
    total = 0
    for location in locations:
        total += await _check_location(session, location, provider)
    return total


def run_official_warnings_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: WeatherProvider | None = None,
) -> OfficialWarningsCycleSummary:
    settings = settings or get_settings()
    if not settings.official_warnings_enabled:
        return OfficialWarningsCycleSummary(enabled=False)

    provider = provider or get_weather_provider(settings)
    locations = list(session.scalars(select(Location).where(Location.is_active.is_(True))))

    alerts_created = asyncio.run(_run_all_locations(session, locations, provider))

    return OfficialWarningsCycleSummary(
        enabled=True,
        locations_checked=len(locations),
        alerts_created=alerts_created,
    )
