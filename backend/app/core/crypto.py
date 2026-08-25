"""Field-level encryption at rest for user PII (ADR-0055).

Two independent keys, both AES-256/HMAC-SHA256-strength (32 raw bytes,
base64-encoded in `Settings`):

- `field_encryption_key` — AES-256-GCM, one random nonce per call, so the
  same plaintext never produces the same ciphertext twice. Used for the
  actual column value (`email`, `full_name`, `google_sub`, the audit-log
  email snapshots).
- `field_encryption_index_key` — HMAC-SHA256, deterministic on purpose.
  AES-GCM's random nonce means the encrypted column itself can never be
  used for `WHERE column = value` or a UNIQUE constraint — two rows with
  the identical plaintext get different ciphertext. The blind index gives
  those columns something deterministic to filter/constrain on, without
  storing (or letting a DB-only attacker recover) the plaintext: a leaked
  index value only proves two rows share the same underlying value, never
  what that value is.

Never reuse one key for both jobs — an attacker who can request encryption
of chosen input under a deterministic-nonce/HMAC key can start recovering
the AEAD key; kept fully separate per standard practice.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_NONCE_LEN = 12  # standard AES-GCM nonce size


def _encryption_key() -> bytes:
    return base64.b64decode(get_settings().field_encryption_key.get_secret_value())


def _index_key() -> bytes:
    return base64.b64decode(get_settings().field_encryption_index_key.get_secret_value())


def encrypt_field(plaintext: str) -> str:
    """AES-256-GCM encrypt; returns base64(nonce || ciphertext‖tag)."""
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_field(token: str) -> str:
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    plaintext = AESGCM(_encryption_key()).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def blind_index(value: str) -> str:
    """Deterministic HMAC-SHA256 hex digest — the actual lookup/uniqueness
    key for an encrypted column (see module docstring). Callers are
    responsible for normalizing `value` (e.g. lower-casing an email)
    themselves before calling this, same as they already must before
    comparing/storing the plaintext."""
    return hmac.new(_index_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
