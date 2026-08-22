"""OpenTelemetry metrics setup (hardening ADR-0035).

Exports metrics to the console by default (same as ``app.core.tracing`` —
visible with zero external infra); additionally via OTLP/HTTP when
``settings.otel_exporter_otlp_endpoint`` is configured. ``configure_metrics``
is skipped in the ``test`` environment for the same reason
``configure_tracing`` is — the OTel SDK enforces a single global
``MeterProvider`` per process, and each test creates a fresh FastAPI app.

Every instrument below only ever takes non-identifying attributes (pipeline
name, provider name, alert event type, notification channel) — never a user
id, tenant id, email, IP, or token. Recording a metric must never require
looking at anything from a specific person's data.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource

from app import __version__
from app.core.config import Settings

# Module-level instruments via the OTel API's meter — safe to create before
# `configure_metrics()` ever runs (the API returns a proxy that attaches to
# the real SDK provider once `set_meter_provider` is called; recording into
# it before that, e.g. in the `test` environment where metrics are never
# configured, is a harmless no-op).
_meter = metrics.get_meter("stormpulse.backend")

pipeline_cycle_duration = _meter.create_histogram(
    "stormpulse.pipeline.cycle_duration",
    unit="s",
    description="Duration of one worker pipeline cycle",
)
pipeline_cycle_failures = _meter.create_counter(
    "stormpulse.pipeline.cycle_failures",
    description="Worker pipeline cycles that raised an exception",
)
weather_source_used = _meter.create_counter(
    "stormpulse.weather.source_used",
    description="Weather provider calls, by provider name and whether it was a fallback",
)
weather_data_age = _meter.create_histogram(
    "stormpulse.weather.data_age",
    unit="s",
    description="Age of weather data at the moment it was used (observed_at to now)",
)
alerts_generated = _meter.create_counter(
    "stormpulse.alerts.generated",
    description="Alerts emitted, by event type",
)
alerts_suppressed = _meter.create_counter(
    "stormpulse.alerts.suppressed",
    description="Alerts/notifications suppressed (antispam, idempotency, no subscription)",
)
notification_failures = _meter.create_counter(
    "stormpulse.notifications.failures",
    description="Notification delivery failures, by channel",
)
external_api_latency = _meter.create_histogram(
    "stormpulse.external_api.latency",
    unit="s",
    description="Latency of outbound calls to external weather/satellite/lightning APIs",
)


def configure_metrics(settings: Settings) -> None:
    resource = Resource.create(
        {
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: __version__,
            "deployment.environment": settings.environment,
        }
    )
    readers = [PeriodicExportingMetricReader(ConsoleMetricExporter())]
    if settings.otel_exporter_otlp_endpoint:
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=settings.otel_exporter_otlp_endpoint)
            )
        )
    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)


def record_weather_data_age(observed_at: datetime, provider: str) -> None:
    """Age of a piece of weather data at the moment it was actually used
    (served to a client, fed into the engine) — how stale is what we're
    showing right now."""
    age = (datetime.now(UTC) - observed_at).total_seconds()
    weather_data_age.record(max(age, 0.0), {"provider": provider})


@contextmanager
def track_pipeline_cycle(pipeline: str) -> Iterator[None]:
    """Records duration (always) and a failure count (only on exception).

    Usage: ``with track_pipeline_cycle("ingestion"): ...cycle body...``
    """
    start = time.monotonic()
    try:
        yield
    except Exception:
        pipeline_cycle_failures.add(1, {"pipeline": pipeline})
        raise
    finally:
        pipeline_cycle_duration.record(time.monotonic() - start, {"pipeline": pipeline})
