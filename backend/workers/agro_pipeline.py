"""Agronomic advisory pipeline (FASE 19).

Two discrete, notification-worthy events, evaluated per monitored
``Location`` on its own schedule (every 6h — see ``workers/tasks.py`` /
``workers/celery_app.py`` — frost/dry-spell don't change minute to minute
like storms, and running less often is kinder to INMET, which the rainfall
history check calls once per day requested per location):

- **Frost** (``FROST_WARNING``): every forecast day is classified into one
  of two tiers — severe (``temperature_min_c`` at/below
  ``settings.agro_frost_threshold_c``, default 3.0°C) or light (at/below
  ``settings.agro_frost_light_threshold_c``, default 6.0°C) — same
  two-threshold idea as Agritempo's frost forecast (ADR-0018). One alert
  per location per day lists every affected date and its tier, rather than
  a single yes/no for "any day". Thresholds are generic agronomic
  references, not tuned to any specific crop; see ADR-0014.
- **Dry spell** (``DRY_SPELL_WARNING``): N consecutive most-recent days with
  measured rainfall below ``settings.agro_dry_spell_rain_threshold_mm`` at
  the nearest station. Deliberately called a "dry spell" (sequência sem
  chuva), never "veranico" — that term implies a deviation from the
  expected rainy-season pattern, which would need climatological normals we
  don't have. This only ever claims "N days without measurable rain."

Own decision logic, not ``app.alerts.engine.AlertEngine`` — that engine is
built around ``RiskAssessment`` hazard scores (rain/wind/hail/lightning
0-1), which neither signal here has; forcing one would mean inventing a
number. Same reasoning already applied to satellite watches (ADR-0009),
whose ``workers/satellite_pipeline.py`` this module mirrors structurally.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.core.enums import AlertEventType, NotificationChannel, NotificationStatus, RiskLevel
from app.locations.models import Location
from app.notifications.models import Notification
from app.weather.factory import get_weather_provider
from app.weather.provider import (
    DailyRainfall,
    ForecastPoint,
    WeatherProvider,
    WeatherProviderUnavailableError,
)

logger = logging.getLogger(__name__)

_FROST_LEVEL = RiskLevel.RED
_FROST_LIGHT_LEVEL = RiskLevel.YELLOW
_DRY_SPELL_LEVEL = RiskLevel.ORANGE
_RECOVERABLE = (WeatherProviderUnavailableError, httpx.HTTPError)


@dataclass
class AgroCycleSummary:
    enabled: bool
    locations_checked: int = 0
    frost_alerts: int = 0
    dry_spell_alerts: int = 0


def _dedup_key(event: AlertEventType, location_id: object, marker: str) -> str:
    return f"{location_id}:{marker}:{event.value}"


def _emit_alert(
    session: Session,
    *,
    location: Location,
    event: AlertEventType,
    level: RiskLevel,
    title: str,
    message: str,
    dedup_key: str,
) -> bool:
    """Idempotent alert emission — same dedup_key pattern as satellite_pipeline.py."""
    already = session.scalars(
        select(Alert).where(Alert.tenant_id == location.tenant_id, Alert.dedup_key == dedup_key)
    ).first()
    if already is not None:
        return False

    alert = Alert(
        tenant_id=location.tenant_id,
        user_id=location.user_id,
        location_id=location.id,
        event_type=event,
        level=level,
        title=title,
        message=message,
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
    return True


def dry_streak_days(daily: list[DailyRainfall], threshold_mm: float) -> int:
    """Consecutive most-recent days with rainfall below ``threshold_mm``.

    Stops at the first gap in the data (a day we simply don't have a
    reading for — never assumed dry) or the first day at/above the
    threshold. Pure function, no I/O — unit-tested directly.
    """
    ordered = sorted(daily, key=lambda d: d.date, reverse=True)
    if not ordered:
        return 0
    streak = 0
    expected_date = ordered[0].date
    for entry in ordered:
        if entry.date != expected_date:
            break
        if entry.total_mm >= threshold_mm:
            break
        streak += 1
        expected_date = entry.date - timedelta(days=1)
    return streak


def classify_frost_days(
    points: list[ForecastPoint], *, severe_threshold_c: float, light_threshold_c: float
) -> tuple[list[ForecastPoint], list[ForecastPoint]]:
    """Split forecast points into (severe, light) frost-risk tiers.

    Severe: ``temperature_min_c <= severe_threshold_c`` (default 3°C —
    established radiative-frost onset reference). Light: at or below
    ``light_threshold_c`` (default 6°C) but above the severe one — an
    earlier warning tier, same idea as Agritempo's two-threshold frost
    forecast. Pure function, no I/O — unit-tested directly. Ordered by
    date, earliest first.
    """
    with_min = [p for p in points if p.temperature_min_c is not None]
    ordered = sorted(with_min, key=lambda p: p.time)
    severe = [p for p in ordered if p.temperature_min_c <= severe_threshold_c]  # type: ignore[operator]
    light = [
        p
        for p in ordered
        if severe_threshold_c < p.temperature_min_c <= light_threshold_c  # type: ignore[operator]
    ]
    return severe, light


def _format_frost_days(points: list[ForecastPoint]) -> str:
    return ", ".join(f"{p.time.strftime('%d/%m')} ({p.temperature_min_c:.1f}°C)" for p in points)


async def _check_frost(
    session: Session,
    location: Location,
    provider: WeatherProvider,
    settings: Settings,
    now: datetime,
) -> bool:
    try:
        forecast = await provider.get_forecast(location.latitude, location.longitude)
    except _RECOVERABLE as exc:
        logger.warning("agro: forecast unavailable for location %s (%s)", location.id, exc)
        return False

    severe, light = classify_frost_days(
        forecast.points,
        severe_threshold_c=settings.agro_frost_threshold_c,
        light_threshold_c=settings.agro_frost_light_threshold_c,
    )
    if not severe and not light:
        return False

    parts = []
    if severe:
        parts.append(
            f"Geada forte prevista (≤{settings.agro_frost_threshold_c:.1f}°C): "
            f"{_format_frost_days(severe)}"
        )
    if light:
        parts.append(
            f"Risco leve de geada (≤{settings.agro_frost_light_threshold_c:.1f}°C): "
            f"{_format_frost_days(light)}"
        )

    today_str = now.date().isoformat()
    return _emit_alert(
        session,
        location=location,
        event=AlertEventType.FROST_WARNING,
        level=_FROST_LEVEL if severe else _FROST_LIGHT_LEVEL,
        title=f"Risco de geada em {location.name}",
        message=" · ".join(parts) + ".",
        dedup_key=_dedup_key(AlertEventType.FROST_WARNING, location.id, today_str),
    )


async def _check_dry_spell(
    session: Session,
    location: Location,
    provider: WeatherProvider,
    settings: Settings,
    now: datetime,
) -> bool:
    try:
        rainfall = await provider.get_recent_rainfall(
            location.latitude, location.longitude, days=settings.agro_dry_spell_window_days
        )
    except _RECOVERABLE as exc:
        logger.warning("agro: rainfall history unavailable for location %s (%s)", location.id, exc)
        return False

    # Exclude today: a partial day (readings so far, not the full 24h) would
    # understate the true total and could falsely extend the streak.
    past_days = [d for d in rainfall.daily if d.date < now.date()]
    streak = dry_streak_days(past_days, settings.agro_dry_spell_rain_threshold_mm)
    if streak < settings.agro_dry_spell_min_days:
        return False

    # The streak can never exceed how many days of history we fetched
    # (`agro_dry_spell_window_days`) — if it hit exactly that ceiling, the
    # real dry spell may well be longer than we can see, so say "pelo menos"
    # instead of implying we know the exact count.
    streak_prefix = "pelo menos " if streak >= settings.agro_dry_spell_window_days else ""

    today_str = now.date().isoformat()
    return _emit_alert(
        session,
        location=location,
        event=AlertEventType.DRY_SPELL_WARNING,
        level=_DRY_SPELL_LEVEL,
        title=f"Sequência sem chuva em {location.name}",
        message=(
            f"{streak_prefix}{streak} dias consecutivos sem chuva mensurável (abaixo de "
            f"{settings.agro_dry_spell_rain_threshold_mm:.1f}mm) na estação mais próxima."
        ),
        dedup_key=_dedup_key(AlertEventType.DRY_SPELL_WARNING, location.id, today_str),
    )


async def _run_all_locations(
    session: Session,
    locations: list[Location],
    provider: WeatherProvider,
    settings: Settings,
    now: datetime,
) -> tuple[int, int]:
    frost_count = 0
    dry_spell_count = 0
    for location in locations:
        if await _check_frost(session, location, provider, settings, now):
            frost_count += 1
        if await _check_dry_spell(session, location, provider, settings, now):
            dry_spell_count += 1
    return frost_count, dry_spell_count


def run_agro_advisory_cycle(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: WeatherProvider | None = None,
) -> AgroCycleSummary:
    settings = settings or get_settings()
    if not settings.agro_enabled:
        return AgroCycleSummary(enabled=False)

    provider = provider or get_weather_provider(settings)
    locations = list(session.scalars(select(Location).where(Location.is_active.is_(True))))
    now = datetime.now(UTC)

    frost_count, dry_spell_count = asyncio.run(
        _run_all_locations(session, locations, provider, settings, now)
    )

    return AgroCycleSummary(
        enabled=True,
        locations_checked=len(locations),
        frost_alerts=frost_count,
        dry_spell_alerts=dry_spell_count,
    )
