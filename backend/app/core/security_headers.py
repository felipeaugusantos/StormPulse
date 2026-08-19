"""HTTP middleware: baseline security response headers.

No Content-Security-Policy here on purpose — a strict CSP would break the
Swagger UI served at ``/docs`` (inline scripts/styles). Documented as a known
limitation in ADR-0007.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds baseline hardening headers to every response.

    ``Strict-Transport-Security`` is only added in production — sending it
    over plain local-dev HTTP would be misleading (browsers ignore it there,
    but it doesn't belong in a dev response either).
    """

    def __init__(self, app: object, *, hsts: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(_STATIC_HEADERS)
        if self._hsts:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
