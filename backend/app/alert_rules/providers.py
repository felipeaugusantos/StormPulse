"""Delivery providers for custom alert channels (Fase 3, ADR-0086).

Email and push already have real, working implementations elsewhere
(``workers/notification_pipeline.py``) — this module only adds what didn't
exist before: webhook (signed, real) and WhatsApp/SMS (abstraction +
explicit mock, no real provider contract exists yet — same "never invent
data, document what a real provider would need" rule the project already
follows for NDVI/deforestation/lightning).
"""

from __future__ import annotations

import abc
import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_SIGNATURE_HEADER = "X-StormPulse-Signature"


def sign_webhook_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex digest of the raw request body — same
    ``hmac.new(key, msg, hashlib.sha256)`` primitive already used in this
    codebase (``app.core.crypto.blind_index``), a **different** key
    (``AlertChannel.webhook_secret_encrypted``, decrypted) and purpose
    (proving *StormPulse* sent this request, not indexing a column) —
    never reuse the field-encryption index key for this."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def send_webhook(
    *, url: str, secret: str, body: bytes, client: httpx.AsyncClient, timeout_seconds: float = 10.0
) -> None:
    """POSTs `body` (already-serialized JSON bytes) to `url` with the HMAC
    signature in `X-StormPulse-Signature`. Raises on any non-2xx response
    or transport error — the caller (the delivery worker) is responsible
    for turning that into a retry, same as every other channel."""
    signature = sign_webhook_payload(secret, body)
    response = await client.post(
        url,
        content=body,
        headers={"Content-Type": "application/json", _WEBHOOK_SIGNATURE_HEADER: signature},
        timeout=timeout_seconds,
    )
    response.raise_for_status()


class WhatsAppSmsProviderUnavailableError(RuntimeError):
    """Raised when no real WhatsApp/SMS provider is configured — never
    silently swallowed, so the delivery worker records a real failure/
    retry instead of a fabricated success."""


class WhatsAppSmsProvider(abc.ABC):
    """Abstraction only — Fase 3's spec explicitly asks for "abstrações
    para WhatsApp e SMS", not a working integration (neither a WhatsApp
    Business API contract nor an SMS gateway contract exists for this
    project yet). A real implementation would need, at minimum: for
    WhatsApp, a Meta Business/WhatsApp Cloud API access token + a
    pre-approved message template (WhatsApp forbids free-form outbound
    messages outside a 24h user-initiated session); for SMS, a gateway
    account (Twilio/Zenvia/etc.) with a sender ID registered for Brazil.
    Neither credential exists in this project's configuration today."""

    @abc.abstractmethod
    async def send(self, *, phone_number: str, message: str) -> None: ...


class MockWhatsAppSmsProvider(WhatsAppSmsProvider):
    """The only provider registered today — always raises
    `WhatsAppSmsProviderUnavailableError`, logged once per attempt. Mirrors
    how NDVI/deforestation/lightning degrade when unconfigured: an honest,
    explicit "not available", never a fabricated delivery."""

    async def send(self, *, phone_number: str, message: str) -> None:
        # Same LGPD-driven pattern as workers/email.py::_correlation_hash —
        # a hash for log correlation, never the phone number itself.
        phone_hash = hashlib.sha256(phone_number.encode("utf-8")).hexdigest()[:12]
        logger.warning(
            "alert_rules: WhatsApp/SMS provider not configured — message not sent",
            extra={"phone_hash": phone_hash},
        )
        raise WhatsAppSmsProviderUnavailableError(
            "Nenhum provider real de WhatsApp/SMS configurado nesta instância."
        )
