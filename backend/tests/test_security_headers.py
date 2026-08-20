"""Tests for SecurityHeadersMiddleware.

The ``hsts=True`` case is tested against the middleware directly (a minimal
Starlette app), not via ``create_app(environment="production")`` — the real
app would also spin up OTel's global TracerProvider as a side effect, which
outlives the test process and is irrelevant to what's being verified here.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import Settings
from app.core.security_headers import SecurityHeadersMiddleware
from app.main import create_app


async def _ok(request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _minimal_app(*, hsts: bool) -> Starlette:
    app = Starlette(routes=[Route("/ping", _ok)])
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return app


async def test_baseline_security_headers_are_present() -> None:
    app = create_app(Settings(environment="test", log_json=False, log_level="WARNING"))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "Strict-Transport-Security" not in resp.headers


async def test_csp_is_absent_on_docs_routes() -> None:
    app = create_app(Settings(environment="test", log_json=False, log_level="WARNING"))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        resp = await client.get("/docs")
    assert "Content-Security-Policy" not in resp.headers
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


async def test_hsts_header_is_added_when_enabled() -> None:
    app = _minimal_app(hsts=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ping")
    assert "max-age=" in resp.headers["Strict-Transport-Security"]


async def test_hsts_header_is_absent_when_disabled() -> None:
    app = _minimal_app(hsts=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/ping")
    assert "Strict-Transport-Security" not in resp.headers
