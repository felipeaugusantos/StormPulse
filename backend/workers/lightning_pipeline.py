"""Lightning-strike detection pipeline (API-REDEMET STSC, FASE 23).

Fetches the current snapshot of atmospheric-discharge (lightning) occurrence
points from DECEA's REDEMET API — a live instrument reading, not a
forecast — and replaces the previous snapshot: every ``LightningStrike``
older than ``settings.lightning_retention_minutes`` is pruned each cycle,
same "instantaneous, always fresh" spirit as ``SatelliteImage``
(``workers/satellite_pipeline.py``). Off by default
(``settings.lightning_enabled=False``) — needs a free registered API key,
see ADR-0019.

Sync ``httpx.Client`` (not async), same choice already made in
``satellite_pipeline.py`` for the same reason: Celery tasks are
synchronous, and there's no async ``WeatherProvider``-style abstraction
this fits (STSC returns a nationwide point list, not per-coordinate
current-conditions/forecast).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.lightning.models import LightningStrike

logger = logging.getLogger(__name__)


@dataclass
class LightningCycleSummary:
    enabled: bool
    points_fetched: int = 0
    points_active: int = 0


def parse_stsc_points(payload: dict[str, Any]) -> list[tuple[float, float]]:
    """Extract the most recent frame's (latitude, longitude) points.

    ``data.stsc`` is a list of animation frames, each a list of
    ``{"la": ..., "lo": ...}`` — the last frame is the most recent. Pure
    function, no I/O — unit-tested directly against the real shape
    documented by DECEA.
    """
    frames = payload.get("data", {}).get("stsc")
    if not frames:
        return []
    latest_frame = frames[-1]
    points: list[tuple[float, float]] = []
    for entry in latest_frame:
        try:
            points.append((float(entry["la"]), float(entry["lo"])))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _fetch_stsc(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    assert settings.redemet_api_key is not None  # guarded by the caller
    response = client.get(
        f"{settings.redemet_base_url}/produtos/stsc",
        headers={"X-Api-Key": settings.redemet_api_key.get_secret_value()},
        timeout=settings.lightning_http_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected API-REDEMET STSC response shape.")
    return data


def _prune_stale_strikes(session: Session, *, older_than: timedelta) -> None:
    cutoff = datetime.now(UTC) - older_than
    stale = session.scalars(
        select(LightningStrike).where(LightningStrike.detected_at < cutoff)
    ).all()
    for strike in stale:
        session.delete(strike)


def run_lightning_detection_cycle(
    session: Session, *, settings: Settings | None = None, client: httpx.Client | None = None
) -> LightningCycleSummary:
    settings = settings or get_settings()
    if not settings.lightning_enabled:
        return LightningCycleSummary(enabled=False)
    if settings.redemet_api_key is None:
        logger.warning("lightning: LIGHTNING_ENABLED=true but REDEMET_API_KEY is not set")
        return LightningCycleSummary(enabled=True)

    own_client = client is None
    client = client or httpx.Client()
    try:
        payload = _fetch_stsc(client, settings)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("lightning: STSC fetch failed (%s)", exc)
        return LightningCycleSummary(enabled=True)
    finally:
        if own_client:
            client.close()

    points = parse_stsc_points(payload)
    now = datetime.now(UTC)
    for latitude, longitude in points:
        session.add(
            LightningStrike(detected_at=now, latitude=latitude, longitude=longitude, is_mock=False)
        )

    _prune_stale_strikes(
        session, older_than=timedelta(minutes=settings.lightning_retention_minutes)
    )
    session.flush()
    active_count = session.scalar(select(func.count()).select_from(LightningStrike)) or 0

    return LightningCycleSummary(
        enabled=True, points_fetched=len(points), points_active=active_count
    )
