"""Unit tests for the SES/SMTP transactional email module (FASE 8,
ADR-0059/ADR-0092).

No real AWS/SMTP call ever happens here — `boto3.client`/`smtplib.SMTP*`
are monkeypatched, mirroring how `pywebpush.webpush` is mocked in
test_notification_pipeline.py. No Postgres/Redis needed.
"""

from __future__ import annotations

import email
import email.header
import smtplib
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


def test_send_email_skips_when_smtp_not_fully_configured() -> None:
    settings = Settings(environment="test", email_provider="smtp", smtp_host="smtp.gmail.com")
    content = render_email("email_verification", link="https://example.com")
    sent = send_email("someone@example.com", content, settings)
    assert sent is False


class _FakeSmtpServer:
    """Mimics `smtplib.SMTP`'s context-manager protocol and the two calls
    `_send_via_smtp` makes — `login`/`sendmail` — recording enough to
    assert on without a real socket."""

    instances: list[_FakeSmtpServer] = []

    def __init__(self, host: str, port: int, timeout: int = 10) -> None:
        self.host = host
        self.port = port
        self.login_calls: list[tuple[str, str]] = []
        self.sendmail_calls: list[tuple[str, list[str], str]] = []
        self.starttls_called = False
        _FakeSmtpServer.instances.append(self)

    def __enter__(self) -> _FakeSmtpServer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        self.sendmail_calls.append((from_addr, to_addrs, msg))


def test_send_email_calls_smtp_starttls_when_configured(monkeypatch: Any) -> None:
    _FakeSmtpServer.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtpServer)

    settings = Settings(
        environment="test",
        email_provider="smtp",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="mefasistemas@gmail.com",
        smtp_password="an-app-password",
    )
    content = render_email("password_reset", link="https://example.com/reset")
    sent = send_email("someone@example.com", content, settings)

    assert sent is True
    assert len(_FakeSmtpServer.instances) == 1
    server = _FakeSmtpServer.instances[0]
    assert server.starttls_called is True
    assert server.login_calls == [("mefasistemas@gmail.com", "an-app-password")]
    from_addr, to_addrs, msg = server.sendmail_calls[0]
    assert from_addr == "mefasistemas@gmail.com"
    assert to_addrs == ["someone@example.com"]
    # The subject has non-ASCII characters ("—"), so it's MIME-encoded
    # (RFC 2047) in the raw message rather than appearing literally.
    parsed = email.message_from_string(msg)
    decoded_subject = str(email.header.make_header(email.header.decode_header(parsed["Subject"])))
    assert decoded_subject == content.subject


def test_send_email_calls_smtp_ssl_for_port_465(monkeypatch: Any) -> None:
    _FakeSmtpServer.instances = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSmtpServer)

    settings = Settings(
        environment="test",
        email_provider="smtp",
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        smtp_username="mefasistemas@gmail.com",
        smtp_password="an-app-password",
    )
    content = render_email("password_reset", link="https://example.com/reset")
    sent = send_email("someone@example.com", content, settings)

    assert sent is True
    server = _FakeSmtpServer.instances[0]
    # Implicit TLS from the first byte — never a separate STARTTLS upgrade.
    assert server.starttls_called is False


def test_send_email_returns_false_on_smtp_error(monkeypatch: Any) -> None:
    class _FailingServer:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def __enter__(self) -> _FailingServer:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def starttls(self) -> None:
            raise smtplib.SMTPConnectError(421, "nope")

    monkeypatch.setattr(smtplib, "SMTP", _FailingServer)

    settings = Settings(
        environment="test",
        email_provider="smtp",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_username="mefasistemas@gmail.com",
        smtp_password="an-app-password",
    )
    content = render_email("email_verification", link="https://example.com/verify")
    sent = send_email("someone@example.com", content, settings)
    assert sent is False
