"""Integration tests for CORS (hardening ADR-0029) — confirms the
allow-list is enforced and never combined with a wildcard origin while
credentials are allowed (that combination is invalid per the CORS spec and
would be a real cross-site vulnerability if it ever slipped in)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

_ALLOWED_ORIGIN = "http://localhost:5173"
_DISALLOWED_ORIGIN = "https://evil.example.com"


async def test_allowed_origin_gets_cors_headers_with_credentials(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"Origin": _ALLOWED_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == _ALLOWED_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


async def test_disallowed_origin_gets_no_cors_headers(client: AsyncClient) -> None:
    resp = await client.get("/health", headers={"Origin": _DISALLOWED_ORIGIN})
    # The request itself still succeeds (CORS is enforced by the browser,
    # not the server refusing the response) — but no
    # Access-Control-Allow-Origin means the browser's fetch()/XHR will
    # block the page from reading the response.
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


async def test_preflight_for_disallowed_origin_is_rejected(client: AsyncClient) -> None:
    resp = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": _DISALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in resp.headers
