"""Unit tests for hCaptcha verification (FASE 8, ADR-0059).

Network calls are faked with ``httpx.MockTransport`` (no live requests, no
extra dependency) — same pattern as ``test_weather_inmet.py`` — so the
real HTTP-calling body of ``verify_captcha`` is actually exercised, not
just its two early-return branches (unconfigured / missing token).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from app.core.captcha import verify_captcha
from app.core.config import Settings


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")


async def test_returns_true_when_unconfigured() -> None:
    settings = Settings(environment="test", hcaptcha_secret_key=None)
    assert await verify_captcha(None, settings, remote_ip=None) is True
    assert await verify_captcha("whatever", settings, remote_ip=None) is True


async def test_returns_false_when_configured_but_token_missing() -> None:
    settings = Settings(environment="test", hcaptcha_secret_key="test-secret")
    assert await verify_captcha(None, settings, remote_ip=None) is False
    assert await verify_captcha("", settings, remote_ip=None) is False


async def test_returns_true_on_successful_verification() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/siteverify"
        return httpx.Response(200, json={"success": True})

    settings = Settings(environment="test", hcaptcha_secret_key="test-secret")
    result = await verify_captcha(
        "a-real-token", settings, remote_ip="1.2.3.4", client=_client(handler)
    )
    assert result is True


async def test_returns_false_when_hcaptcha_rejects_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": False, "error-codes": ["invalid-input-response"]}
        )

    settings = Settings(environment="test", hcaptcha_secret_key="test-secret")
    result = await verify_captcha("bad-token", settings, remote_ip=None, client=_client(handler))
    assert result is False


async def test_returns_false_when_hcaptcha_api_is_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = Settings(environment="test", hcaptcha_secret_key="test-secret")
    result = await verify_captcha("a-token", settings, remote_ip=None, client=_client(handler))
    assert result is False


async def test_returns_false_on_hcaptcha_http_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    settings = Settings(environment="test", hcaptcha_secret_key="test-secret")
    result = await verify_captcha("a-token", settings, remote_ip=None, client=_client(handler))
    assert result is False
