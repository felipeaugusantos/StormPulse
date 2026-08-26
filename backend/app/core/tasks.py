"""Lightweight Celery client so the API can enqueue an on-demand pipeline
run (admin "atualizar agora" button, FASE 34 follow-up) without depending
on ``workers/`` at all.

Deliberately does NOT import ``workers.celery_app``/``workers.tasks`` —
those pull in GDAL/TATHU-only code (``workers/satellite_pipeline.py``)
that the ``api`` image doesn't have (only the ``worker`` image's
``-satellite`` variant does; see ADR-0041). Sending a task by name only
needs a broker connection, never the task body itself, so a throwaway
``Celery`` producer client is enough.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import Settings

# Maps the same `name` PipelineHealthOut reports (app/admin/schemas.py) to
# the real Celery task name (workers/tasks.py) — kept in sync manually
# since app/ doesn't import workers/.
PIPELINE_TASK_NAMES: dict[str, str] = {
    "satellite": "workers.tasks.run_satellite_detection_task",
    "storms": "workers.tasks.run_ingestion_cycle_task",
    "lightning": "workers.tasks.run_lightning_detection_task",
}


def trigger_pipeline(name: str, settings: Settings) -> None:
    """Enqueue one immediate run of the named pipeline — fire-and-forget,
    picked up by whichever `worker` is consuming the queue next. Raises
    `KeyError` for an unknown `name` (checked by the caller for a clean
    404, not exposed as a raw KeyError)."""
    task_name = PIPELINE_TASK_NAMES[name]
    client = Celery("stormpulse-api-sender", broker=settings.redis_url)
    client.send_task(task_name)


def send_transactional_email(kind: str, to_email: str, link: str, settings: Settings) -> None:
    """Enqueue one account-cycle email (verification/password reset,
    FASE 8) — same fire-and-forget shape as `trigger_pipeline` above, so
    /auth/register and /auth/forgot-password never block the response on
    an SES network call. The `api` image never imports `workers.email`
    (which imports `boto3`) directly — this only needs a broker
    connection, the task body lives entirely in the `worker` image."""
    client = Celery("stormpulse-api-sender", broker=settings.redis_url)
    client.send_task("workers.tasks.send_transactional_email_task", args=[kind, to_email, link])
