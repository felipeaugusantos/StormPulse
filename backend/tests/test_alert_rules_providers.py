"""Tests for app/alert_rules/providers.py — webhook HMAC signing and the
WhatsApp/SMS mock (Fase 3, ADR-0086)."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from app.alert_rules.providers import (
    MockWhatsAppSmsProvider,
    WhatsAppSmsProviderUnavailableError,
    send_webhook,
    sign_webhook_payload,
)


def test_sign_webhook_payload_matches_manual_hmac() -> None:
    body = b'{"event":"test"}'
    expected = hmac.new(b"my-secret", body, hashlib.sha256).hexdigest()
    assert sign_webhook_payload("my-secret", body) == expected


def test_sign_webhook_payload_differs_with_different_secrets() -> None:
    body = b'{"event":"test"}'
    assert sign_webhook_payload("secret-a", body) != sign_webhook_payload("secret-b", body)


async def test_send_webhook_attaches_the_signature_header() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["signature"] = request.headers.get("X-StormPulse-Signature")
        captured["body"] = request.content
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    body = b'{"hello":"world"}'
    await send_webhook(url="https://example.com/hook", secret="shh", body=body, client=client)

    assert captured["signature"] == sign_webhook_payload("shh", body)
    assert captured["body"] == body


async def test_send_webhook_raises_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await send_webhook(url="https://example.com/hook", secret="shh", body=b"{}", client=client)


async def test_mock_whatsapp_sms_provider_always_raises() -> None:
    provider = MockWhatsAppSmsProvider()
    with pytest.raises(WhatsAppSmsProviderUnavailableError):
        await provider.send(phone_number="+5511999999999", message="oi")
