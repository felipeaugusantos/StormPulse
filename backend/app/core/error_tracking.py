"""Sentry error tracking — real gap found live 2026-09-22: none of that
day's incidents (nginx serving a dead upstream IP, worker/beat's own
health check always failing, MinIO pulled off Docker Hub) were caught by
an automated alert, only by someone looking manually.

Separate from OpenTelemetry tracing (``app/core/tracing.py``, ADR-0007) —
that's for following a request's *path* through the system; this is for
"an unhandled exception happened, tell someone now". Skipped entirely
without ``sentry_dsn`` configured (dev/test default) or in the ``test``
environment — same spirit as ``configure_tracing``.
"""

from __future__ import annotations

from app import __version__
from app.core.config import Settings


def configure_error_tracking(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        release=__version__,
        # Error events only — no performance/trace sampling here (that's
        # OpenTelemetry's job already, a second tracing pipeline would
        # just be redundant cost for no new signal).
        traces_sample_rate=0.0,
    )
