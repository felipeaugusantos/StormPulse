"""Celery tasks."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.metrics import (
    alerts_generated,
    alerts_suppressed,
    notification_failures,
    track_pipeline_cycle,
)
from app.storms.models import StormRisk
from workers.agro_pipeline import run_agro_advisory_cycle
from workers.ai_summary import generate_summary
from workers.celery_app import celery_app
from workers.db import session_scope
from workers.deforestation_pipeline import run_deforestation_check_cycle
from workers.email import EmailKind, render_email, send_email
from workers.forecast_comparison_pipeline import fill_observed_values, record_forecast_snapshots
from workers.lightning_pipeline import run_lightning_detection_cycle
from workers.ndvi_pipeline import run_ndvi_pipeline_cycle
from workers.notification_pipeline import run_notification_delivery_cycle
from workers.official_warnings_pipeline import run_official_warnings_cycle
from workers.pipeline_service import run_ingestion_cycle
from workers.satellite_pipeline import run_satellite_detection_cycle
from workers.zarc_pipeline import run_zarc_ingestion_cycle

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.run_ingestion_cycle_task")
def run_ingestion_cycle_task() -> dict[str, Any]:
    """Run one ingestion → engine → risk → alert cycle."""
    with track_pipeline_cycle("ingestion"), session_scope() as session:
        summary = run_ingestion_cycle(session)
    alerts_generated.add(summary.alerts, {"pipeline": "ingestion"})
    if summary.suppressed:
        alerts_suppressed.add(summary.suppressed, {"reason": "alert_preference"})
    # Dispatched only *after* session_scope()'s commit above — see
    # CycleSummary.risk_ids_for_ai_summary's docstring for why dispatching
    # any earlier (e.g. from inside run_ingestion_cycle, before its own
    # transaction commits) would be a race against the AI summary task's
    # own, separate DB connection.
    for risk_id in summary.risk_ids_for_ai_summary:
        generate_risk_ai_summary_task.delay(risk_id)
    result = {
        "frames": summary.frames,
        "cells": summary.cells,
        "risks": summary.risks,
        "alerts": summary.alerts,
        "suppressed": summary.suppressed,
        "ai_summaries_queued": len(summary.risk_ids_for_ai_summary),
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


@celery_app.task(name="workers.tasks.run_ndvi_pipeline_task")
def run_ndvi_pipeline_task() -> dict[str, Any]:
    """Run one NDVI-per-talhão cycle (FASE 29).

    No-op (returns immediately) when NDVI_ENABLED=false — the default.
    """
    with track_pipeline_cycle("ndvi"), session_scope() as session:
        summary = run_ndvi_pipeline_cycle(session)
    result = {
        "enabled": summary.enabled,
        "talhoes_checked": summary.talhoes_checked,
        "readings_created": summary.readings_created,
        "failures": summary.failures,
    }
    logger.info("NDVI pipeline cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_deforestation_check_task")
def run_deforestation_check_task() -> dict[str, Any]:
    """Run one DETER/PRODES deforestation-check cycle (item DETER).

    No-op (returns immediately) when DEFORESTATION_CHECK_ENABLED=false —
    the default.
    """
    with track_pipeline_cycle("deforestation"), session_scope() as session:
        summary = run_deforestation_check_cycle(session)
    result = {
        "enabled": summary.enabled,
        "talhoes_checked": summary.talhoes_checked,
        "checks_updated": summary.checks_updated,
        "source_failures": summary.source_failures,
    }
    logger.info("deforestation check cycle complete", extra=result)
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


@celery_app.task(name="workers.tasks.run_forecast_snapshot_task")
def run_forecast_snapshot_task() -> dict[str, Any]:
    """Run one forecast-snapshot cycle (Fase 2 — Comparação e Validação de
    Previsões, ADR-0082): asks Open-Meteo for ECMWF/GFS/ICON side by side
    and stores what each predicted for each active location.

    No-op (returns immediately) when FORECAST_COMPARISON_ENABLED=false or
    WEATHER_PROVIDER=mock — there is no honest mock for this.
    """
    with track_pipeline_cycle("forecast_snapshot"), session_scope() as session:
        summary = record_forecast_snapshots(session)
    result = {
        "enabled": summary.enabled,
        "locations_checked": summary.locations_checked,
        "snapshots_recorded": summary.snapshots_recorded,
    }
    logger.info("forecast snapshot cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_forecast_observation_fill_task")
def run_forecast_observation_fill_task() -> dict[str, Any]:
    """Run one observation-fill cycle (Fase 2 — Comparação e Validação de
    Previsões, ADR-0082): fills in what actually happened for snapshots
    whose target date has already passed.
    """
    with track_pipeline_cycle("forecast_observation_fill"), session_scope() as session:
        summary = fill_observed_values(session)
    result = {
        "enabled": summary.enabled,
        "observations_filled": summary.observations_filled,
    }
    logger.info("forecast observation fill cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_official_warnings_task")
def run_official_warnings_task() -> dict[str, Any]:
    """Run one official-warnings-to-alerts cycle (item 3, ADR-0064).

    No-op (returns immediately) when OFFICIAL_WARNINGS_ENABLED=false.
    """
    with track_pipeline_cycle("official_warnings"), session_scope() as session:
        summary = run_official_warnings_cycle(session)
    alerts_generated.add(summary.alerts_created, {"pipeline": "official_warnings"})
    result = {
        "enabled": summary.enabled,
        "locations_checked": summary.locations_checked,
        "alerts_created": summary.alerts_created,
    }
    logger.info("official warnings cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.run_zarc_ingestion_task")
def run_zarc_ingestion_task() -> dict[str, Any]:
    """Refresh the ZARC planting-window reference table (item ZARC,
    ADR-0069). No-op (returns immediately) when ZARC_ENABLED=false.
    """
    with track_pipeline_cycle("zarc"), session_scope() as session:
        summary = run_zarc_ingestion_cycle(session)
    result = {"enabled": summary.enabled, "rows_ingested": summary.rows_ingested}
    logger.info("ZARC ingestion task complete", extra=result)
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
        "retrying": summary.retrying,
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


@celery_app.task(name="workers.tasks.send_transactional_email_task")
def send_transactional_email_task(kind: EmailKind, to_email: str, link: str) -> dict[str, Any]:
    """Sends one account-cycle email (verification/password reset, FASE 8)
    fire-and-forget from the request path — see `app.core.tasks.send_transactional_email`
    for the API-side dispatcher. Never raises: a bounced/misconfigured SES
    must not retry-storm the queue; `send_email` already logs the failure."""
    settings = get_settings()
    content = render_email(kind, link=link)
    sent = send_email(to_email, content, settings)
    result = {"kind": kind, "sent": sent}
    logger.info("transactional email cycle complete", extra=result)
    return result


@celery_app.task(name="workers.tasks.generate_risk_ai_summary_task")
def generate_risk_ai_summary_task(risk_id: str) -> dict[str, Any]:
    """Generates and saves the AI summary for one `StormRisk` row already
    committed by `run_ingestion_cycle` (FASE 9, ADR-0060) — dispatched
    fire-and-forget right after that row is created, same shape as the
    email task above, so the ingestion cycle itself never waits on a
    Claude API call. A missing row (deleted before this ran) or an
    unconfigured/failed generation are both silently no-ops, never a
    retry-storm."""
    settings = get_settings()
    with session_scope() as session:
        risk = session.get(StormRisk, uuid.UUID(risk_id))
        if risk is None:
            return {"risk_id": risk_id, "generated": False, "reason": "risk_not_found"}
        summary = generate_summary(risk, settings)
        if summary is None:
            return {"risk_id": risk_id, "generated": False, "reason": "unconfigured_or_failed"}
        risk.ai_summary = summary
    return {"risk_id": risk_id, "generated": True}
