"""Celery application and beat schedule (FASE 10).

Broker and result backend are Redis (already in the stack). Beat drives the
periodic ingestion cycle. See ADR-0002 for why Celery.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "stormpulse",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=300,
    task_acks_late=True,
    worker_max_tasks_per_child=200,
    timezone="UTC",
    beat_schedule={
        "ingest-every-5-minutes": {
            "task": "workers.tasks.run_ingestion_cycle_task",
            "schedule": 300.0,  # seconds
        },
        "satellite-detect-every-10-minutes": {
            "task": "workers.tasks.run_satellite_detection_task",
            "schedule": 600.0,  # seconds — matches GOES-19 full-disk cadence
        },
        "agro-advisory-every-6-hours": {
            "task": "workers.tasks.run_agro_advisory_task",
            # Frost/dry-spell don't change minute to minute like storms, and
            # the rainfall check calls INMET once per day requested per
            # location — less frequent is honest and kinder to the API.
            "schedule": 21_600.0,  # seconds
        },
        "deliver-notifications-every-minute": {
            "task": "workers.tasks.run_notification_delivery_task",
            # Alerts are time-sensitive by nature — deliver pending ones
            # quickly. No-op cost is a single indexed SELECT when the queue
            # is empty.
            "schedule": 60.0,  # seconds
        },
    },
)
