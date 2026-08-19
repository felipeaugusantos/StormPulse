"""Request-scoped context (request/correlation IDs) via contextvars."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_request_id() -> str | None:
    return request_id_var.get()


def get_correlation_id() -> str | None:
    return correlation_id_var.get()
