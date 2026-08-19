"""Structured (JSON) logging with request/correlation IDs.

Uses only the standard library to avoid an extra dependency. When
``log_json`` is disabled a human-friendly text format is used instead.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.core.context import get_correlation_id, get_request_id

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Include any structured `extra=` fields.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextFilter(logging.Filter):
    """Attach request/correlation IDs so the text formatter can show them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.correlation_id = get_correlation_id() or "-"
        return True


def configure_logging(*, level: str = "INFO", json_logs: bool = True) -> None:
    """Configure the root logger. Idempotent."""
    handler = logging.StreamHandler(sys.stdout)
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(ContextFilter())
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s "
                "[req=%(request_id)s corr=%(correlation_id)s] %(message)s"
            )
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Align uvicorn access/error loggers with our handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
