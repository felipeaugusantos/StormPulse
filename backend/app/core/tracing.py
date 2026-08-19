"""OpenTelemetry tracing setup (FASE 14).

Exports spans to the console by default (no external backend required to see
tracing working); additionally exports via OTLP/HTTP when
``settings.otel_exporter_otlp_endpoint`` is configured. Instruments FastAPI,
SQLAlchemy and httpx (the latter also covers ``InmetWeatherProvider``'s HTTP
client from FASE 13, for free).

Skipped entirely in the ``test`` environment — see ``create_app()`` — because
the OTel SDK enforces a single global ``TracerProvider`` per process, and
each test creates a fresh FastAPI app.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app import __version__
from app.core.config import Settings


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create(
        {
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: __version__,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if settings.otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
        )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
