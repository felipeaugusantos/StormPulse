"""Deterministic recommendation-generation cycle (Fase 5, ADR-0089).

Mirrors ``workers/alert_rules_pipeline.py``'s own structure (per-location
error isolation, ``gather_metric_snapshot`` reused unchanged from that
module — same metrics, same provider injection for tests). Unlike the
alert-rules pipeline, there is no per-tenant configuration here: the
catalog in ``engine/recommendations.py`` is fixed and evaluated against
every active location once per cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import Alert
from app.core.config import Settings, get_settings
from app.locations.models import Location
from app.recommendations.models import RecommendedAction
from app.weather.provider import WeatherProvider
from engine.recommendations import RecommendationRule, evaluate_recommendations
from workers.alert_rules_pipeline import gather_metric_snapshot

logger = logging.getLogger(__name__)


@dataclass
class RecommendationCycleSummary:
    locations_evaluated: int = 0
    recommendations_created: int = 0
    recommendations_skipped_duplicate: int = 0


def run_recommendation_cycle(
    session: Session, *, settings: Settings | None = None, provider: WeatherProvider | None = None
) -> RecommendationCycleSummary:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    summary = RecommendationCycleSummary()

    locations = session.scalars(select(Location).where(Location.is_active.is_(True))).all()
    for location in locations:
        summary.locations_evaluated += 1
        try:
            _evaluate_one_location(session, location, settings, now, summary, provider=provider)
        except Exception:  # noqa: BLE001 - one location's failure must never stop the cycle
            logger.exception("recommendations: evaluation failed for location %s", location.id)

    return summary


def _evaluate_one_location(
    session: Session,
    location: Location,
    settings: Settings,
    now: datetime,
    summary: RecommendationCycleSummary,
    *,
    provider: WeatherProvider | None = None,
) -> None:
    snapshot = asyncio.run(gather_metric_snapshot(location, settings, session, provider=provider))
    matched = evaluate_recommendations(snapshot)
    if not matched:
        return

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    snapshot_json = json.dumps(asdict(snapshot))

    for rule in matched:
        already_created_today = session.scalars(
            select(RecommendedAction).where(
                RecommendedAction.location_id == location.id,
                RecommendedAction.rule_key == rule.key,
                RecommendedAction.created_at >= today_start,
            )
        ).first()
        if already_created_today is not None:
            summary.recommendations_skipped_duplicate += 1
            continue

        session.add(
            RecommendedAction(
                tenant_id=location.tenant_id,
                location_id=location.id,
                rule_key=rule.key,
                title=rule.title,
                message=rule.message,
                level=rule.level,
                alert_id=_related_alert_id(session, location, rule, today_start),
                snapshot_json=snapshot_json,
            )
        )
        summary.recommendations_created += 1


def _related_alert_id(
    session: Session, location: Location, rule: RecommendationRule, today_start: datetime
) -> uuid.UUID | None:
    if rule.related_alert_event_type is None:
        return None
    alert = session.scalars(
        select(Alert)
        .where(
            Alert.location_id == location.id,
            Alert.event_type == rule.related_alert_event_type,
            Alert.created_at >= today_start,
        )
        .order_by(Alert.created_at.desc())
    ).first()
    return alert.id if alert is not None else None
