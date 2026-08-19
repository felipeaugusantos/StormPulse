"""Unit tests for password hashing and JWT tokens (no DB required)."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", jwt_secret_key="test-secret-key-0123456789abcdef-32b")


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_access_token_roundtrip(settings: Settings) -> None:
    token = create_access_token("user-123", settings, extra_claims={"role": "user"})
    payload = decode_token(token, settings, expected_type="access")
    assert payload["sub"] == "user-123"
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip(settings: Settings) -> None:
    token = create_refresh_token("user-123", settings)
    payload = decode_token(token, settings, expected_type="refresh")
    assert payload["sub"] == "user-123"


def test_access_token_rejected_as_refresh(settings: Settings) -> None:
    token = create_access_token("user-123", settings)
    with pytest.raises(TokenError):
        decode_token(token, settings, expected_type="refresh")


def test_expired_token_is_rejected(settings: Settings) -> None:
    from app.core.security import _create_token

    token = _create_token(
        subject="user-123",
        token_type="access",
        settings=settings,
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(TokenError):
        decode_token(token, settings, expected_type="access")


def test_wrong_signature_is_rejected(settings: Settings) -> None:
    token = create_access_token("user-123", settings)
    other = Settings(environment="test", jwt_secret_key="a-different-secret-0123456789abcdef-32b")
    with pytest.raises(TokenError):
        decode_token(token, other, expected_type="access")


def test_tampered_token_is_rejected(settings: Settings) -> None:
    token = create_access_token("user-123", settings)
    with pytest.raises(TokenError):
        decode_token(token + "tamper", settings, expected_type="access")
    # sanity: a totally unrelated string also fails
    with pytest.raises(TokenError):
        decode_token("not-a-jwt", settings, expected_type="access")


def test_production_refuses_dev_secret() -> None:
    with pytest.raises(ValueError, match="strong secret"):
        Settings(environment="production")


def test_signing_uses_configured_algorithm(settings: Settings) -> None:
    token = create_access_token("user-123", settings)
    header = jwt.get_unverified_header(token)
    assert header["alg"] == settings.jwt_algorithm
