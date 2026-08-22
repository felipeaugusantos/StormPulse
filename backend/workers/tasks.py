"""Celery tasks."""

from __future__ import annotations

import logging
from typing import Any

from app.core.metrics import (
    alerts_generated,
    alerts_suppressed,
    notification_failures,
    track_pipeline_cycle,
)
from workers.agro_pipeline import run_agro_advisory_cycle
from workers.celery_app import celery_app
from workers.db import session_scope
from workers.lightning_pipeline import run_lightning_detection_cycle
from workers.notification_pipeline import run_notification_delivery_cycle
from workers.pipeline_service import run_ingestion_cycle
from workers.satellite_pipeline import run_satellite_detection_cycle

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.run_ingestion_cycle_task")
def run_ingestion_cycle_task() -> dict[str, Any]:
    """Run one ingestion → engine → risk → alert cycle."""
    with track_pipeline_cycle("ingestion"), session_scope() as session:
        summary = run_ingestion_cycle(session)
    alerts_generated.add(summary.alerts, {"pipeline": "ingestion"})
    result = {
        "frames": summary.frames,
        "cells": summary.cells,
        "risks": summary.risks,
        "alerts": summary.alerts,
    }
    logger.info("ingestion cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_satellite_detection_task")
def run_satellite_detection_task() -> dict[str, Any]:
    """Run one satellite convective-watch detection cycle (FASE 16).

    No-op (returns immediately) when SATELLITE_ENABLED=false — the default.
    """
    with track_pipeline_cycle("satellite"), session_scope() as session:
        summary = run_satellite_detection_cycle(session)
    alerts_generated.add(summary.alerts, {"pipeline": "satellite"})
    result = {
        "enabled": summary.enabled,
        "frames_downloaded": summary.frames_downloaded,
        "systems_detected": summary.systems_detected,
        "watches_active": summary.watches_active,
        "watches_dissipated": summary.watches_dissipated,
        "alerts": summary.alerts,
    }
    logger.info("satellite detection cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_agro_advisory_task")
def run_agro_advisory_task() -> dict[str, Any]:
    """Run one agronomic advisory cycle (frost, dry spell — FASE 19).

    No-op (returns immediately) when AGRO_ENABLED=false.
    """
    with track_pipeline_cycle("agro"), session_scope() as session:
        summary = run_agro_advisory_cycle(session)
    alerts_generated.add(summary.frost_alerts + summary.dry_spell_alerts, {"pipeline": "agro"})
    result = {
        "enabled": summary.enabled,
        "locations_checked": summary.locations_checked,
        "frost_alerts": summary.frost_alerts,
        "dry_spell_alerts": summary.dry_spell_alerts,
    }
    logger.info("agro advisory cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_notification_delivery_task")
def run_notification_delivery_task() -> dict[str, Any]:
    """Deliver pending push notifications (FASE 22).

    No-op (returns immediately) when no VAPID key is configured.
    """
    with track_pipeline_cycle("notification"), session_scope() as session:
        summary = run_notification_delivery_cycle(session)
    if summary.failed:
        notification_failures.add(summary.failed, {"pipeline": "notification"})
    if summary.suppressed:
        alerts_suppressed.add(summary.suppressed, {"reason": "no_subscription_or_unconfigured"})
    result = {
        "configured": summary.configured,
        "attempted": summary.attempted,
        "sent": summary.sent,
        "failed": summary.failed,
        "suppressed": summary.suppressed,
    }
    logger.info("notification delivery cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_lightning_detection_task")
def run_lightning_detection_task() -> dict[str, Any]:
    """Run one lightning-strike detection cycle (API-REDEMET STSC — FASE 23).

    No-op (returns immediately) when LIGHTNING_ENABLED=false — the default.
    """
    with track_pipeline_cycle("lightning"), session_scope() as session:
        summary = run_lightning_detection_cycle(session)
    result = {
        "enabled": summary.enabled,
        "points_fetched": summary.points_fetched,
        "points_active": summary.points_active,
    }
    logger.info("lightning detection cycle complete", extra=result)
    return result
