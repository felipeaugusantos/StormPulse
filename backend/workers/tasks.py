"""Celery tasks."""

from __future__ import annotations

import logging
from typing import Any

from workers.celery_app import celery_app
from workers.db import session_scope
from workers.pipeline_service import run_ingestion_cycle
from workers.satellite_pipeline import run_satellite_detection_cycle

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.run_ingestion_cycle_task")
def run_ingestion_cycle_task() -> dict[str, Any]:
    """Run one ingestion → engine → risk → alert cycle."""
    with session_scope() as session:
        summary = run_ingestion_cycle(session)
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
    with session_scope() as session:
        summary = run_satellite_detection_cycle(session)
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
