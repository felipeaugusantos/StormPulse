"""HTTP middleware: baseline security response headers.

This backend only ever serves JSON (never HTML rendered for an end user), so
a locked-down ``default-src 'none'`` CSP is safe everywhere except the
Swagger/ReDoc docs routes, which need inline scripts/styles to render — those
three paths are exempted below. See ADR-0007/ADR-0016.

This CSP protects API *responses* — it says nothing about the SPA's own HTML
(served separately, by Vite in dev and by a future static host in
production), which needs its own CSP wherever it ends up served.
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
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

# Docs routes render actual HTML with inline scripts/styles (Swagger/ReDoc) —
# the locked-down CSP above would break them, so they get no CSP at all.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


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
        if request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
            response.headers.update(
                {k: v for k, v in _STATIC_HEADERS.items() if k != "Content-Security-Policy"}
            )
        else:
            response.headers.update(_STATIC_HEADERS)
        if self._hsts:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
