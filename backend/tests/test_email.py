"""Unit tests for the SES transactional email module (FASE 8, ADR-0059).

No real AWS call ever happens here — `boto3.client` itself is
monkeypatched, mirroring how `pywebpush.webpush` is mocked in
test_notification_pipeline.py. No Postgres/Redis needed.
"""

from __future__ import annotations

from typing import Any

import boto3

from app.core.config import Settings
from workers.email import render_email, send_email


def test_render_email_verification_includes_the_link() -> None:
    content = render_email("email_verification", link="https://app.example.com/verify?token=abc")
    assert "https://app.example.com/verify?token=abc" in content.text_body
    assert "https://app.example.com/verify?token=abc" in content.html_body
    assert content.subject


def test_render_email_password_reset_includes_the_link() -> None:
    content = render_email("password_reset", link="https://app.example.com/reset?token=xyz")
    assert "https://app.example.com/reset?token=xyz" in content.text_body
    assert "https://app.example.com/reset?token=xyz" in content.html_body
    assert content.subject


def test_send_email_skips_when_ses_from_email_not_configured() -> None:
    settings = Settings(environment="test", ses_from_email=None)
    content = render_email("email_verification", link="https://example.com")
    sent = send_email("someone@example.com", content, settings)
    assert sent is False


class _FakeSesClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"MessageId": "fake-id"}


def test_send_email_calls_ses_when_configured(monkeypatch: Any) -> None:
    fake_client = _FakeSesClient()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake_client)

    settings = Settings(environment="test", ses_from_email="alerts@stormpulse.example")
    content = render_email("password_reset", link="https://example.com/reset")
    sent = send_email("someone@example.com", content, settings)

    assert sent is True
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["Source"] == "alerts@stormpulse.example"
    assert call["Destination"] == {"ToAddresses": ["someone@example.com"]}
    assert call["Message"]["Subject"]["Data"] == content.subject


def test_send_email_returns_false_on_ses_client_error(monkeypatch: Any) -> None:
    from botocore.exceptions import ClientError

    class _FailingClient:
        def send_email(self, **kwargs: Any) -> None:
            raise ClientError(
                {"Error": {"Code": "MessageRejected", "Message": "nope"}}, "SendEmail"
            )

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FailingClient())

    settings = Settings(environment="test", ses_from_email="alerts@stormpulse.example")
    content = render_email("email_verification", link="https://example.com/verify")
    sent = send_email("someone@example.com", content, settings)
    assert sent is False
