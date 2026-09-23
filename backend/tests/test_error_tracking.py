"""Unit tests for Sentry wiring (`app/core/error_tracking.py`).

No real Sentry call ever happens here — `sentry_sdk.init` itself is
monkeypatched, mirroring how `boto3.client`/`smtplib.SMTP` are mocked in
test_email.py. No Postgres/Redis needed.
"""

from __future__ import annotations

from typing import Any

import sentry_sdk

from app.core.config import Settings
from app.core.error_tracking import configure_error_tracking


def test_configure_error_tracking_is_a_noop_without_a_dsn(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    settings = Settings(environment="test", sentry_dsn=None)
    configure_error_tracking(settings)

    assert calls == []


def test_configure_error_tracking_initializes_sentry_when_a_dsn_is_set(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    settings = Settings(
        environment="test", sentry_dsn="https://examplePublicKey@o0.ingest.sentry.io/0"
    )
    configure_error_tracking(settings)

    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
    assert calls[0]["environment"] == "test"
    # No second tracing pipeline — OpenTelemetry already owns performance
    # tracing (ADR-0007); this module is error capture only.
    assert calls[0]["traces_sample_rate"] == 0.0
