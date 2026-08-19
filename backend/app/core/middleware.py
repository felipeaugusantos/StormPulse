"""HTTP middleware: request/correlation ID propagation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import correlation_id_var, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a unique request ID and propagate an inbound correlation ID.

    - ``request_id`` is always freshly generated per request.
    - ``correlation_id`` is taken from the inbound header when present
      (to trace across services/clients) or falls back to the request ID.

    Both are exposed via ``contextvars`` (so logs pick them up) and echoed
    back in the response headers.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id

        req_token = request_id_var.set(request_id)
        corr_token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(req_token)
            correlation_id_var.reset(corr_token)

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
