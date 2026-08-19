"""Celery tasks."""

from __future__ import annotations

import logging
from typing import Any

from workers.celery_app import celery_app
from workers.db import session_scope
from workers.pipeline_service import run_ingestion_cycle

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
