"""Security primitives: password hashing (Argon2) and JWT tokens.

No secrets are hard-coded — the signing key comes from settings. Access and
refresh tokens are distinguished by a ``type`` claim so a refresh token can
never be used as an access token, and vice versa.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

_password_hash = PasswordHash.recommended()

TokenType = Literal["access", "refresh", "email_verification", "password_reset"]


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    settings: Settings,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(
    subject: str, settings: Settings, extra_claims: dict[str, Any] | None = None
) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        settings=settings,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        extra_claims=extra_claims,
    )


def create_refresh_token(subject: str, settings: Settings) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        settings=settings,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def password_fingerprint(hashed_password: str) -> str:
    """Short, non-reversible fingerprint of a user's current password hash
    — embedded as a claim in a password-reset token so that changing the
    password (which changes `hashed_password`) naturally invalidates every
    reset token issued before that change, without a separate DB table to
    track single-use tokens (FASE 8, ADR-0059)."""
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def create_email_verification_token(subject: str, settings: Settings) -> str:
    """24h-lived — verifying twice is harmless, so no single-use tracking
    is needed (unlike the password-reset token below)."""
    return _create_token(
        subject=subject,
        token_type="email_verification",
        settings=settings,
        expires_delta=timedelta(hours=24),
    )


def create_password_reset_token(subject: str, hashed_password: str, settings: Settings) -> str:
    return _create_token(
        subject=subject,
        token_type="password_reset",
        settings=settings,
        expires_delta=timedelta(hours=1),
        extra_claims={"pwd_fp": password_fingerprint(hashed_password)},
    )


class TokenError(Exception):
    """Raised when a token is invalid, expired or of the wrong type."""


def decode_token(token: str, settings: Settings, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT, enforcing the expected token type.

    Raises ``TokenError`` on any problem (bad signature, expiry, wrong type).
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected {expected_type} token, got {payload.get('type')!r}")
    if "sub" not in payload:
        raise TokenError("token missing subject")
    return payload
