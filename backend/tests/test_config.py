"""Tests for settings and derived connection URLs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_url_uses_asyncpg_driver() -> None:
    settings = Settings(
        postgres_host="db",
        postgres_port=5432,
        postgres_user="u",
        postgres_password="p",
        postgres_db="stormpulse",
    )
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/stormpulse"


def test_sync_database_url_uses_psycopg2_driver() -> None:
    settings = Settings(postgres_host="db", postgres_user="u", postgres_password="p")
    assert settings.sync_database_url.startswith("postgresql+psycopg2://")


def test_redis_url_is_built_from_parts() -> None:
    settings = Settings(redis_host="cache", redis_port=6379, redis_db=1)
    assert settings.redis_url == "redis://cache:6379/1"


def test_production_refuses_the_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="production", jwt_secret_key="dev-insecure-change-me")


def test_production_requires_secure_cookie_when_cookie_enabled() -> None:
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            environment="production",
            jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
            refresh_cookie_enabled=True,
            refresh_cookie_secure=False,
        )


def test_samesite_none_requires_secure_cookie_in_any_environment() -> None:
    # Not production-specific — every browser rejects SameSite=None without
    # Secure regardless of environment (Fase 4, ADR-0045).
    with pytest.raises(ValidationError, match="SAMESITE=none requires"):
        Settings(
            environment="local",
            refresh_cookie_enabled=True,
            refresh_cookie_samesite="none",
            refresh_cookie_secure=False,
        )


def test_samesite_none_with_secure_is_accepted() -> None:
    settings = Settings(
        refresh_cookie_enabled=True,
        refresh_cookie_samesite="none",
        refresh_cookie_secure=True,
    )
    assert settings.refresh_cookie_samesite == "none"


def test_samesite_lax_never_requires_secure() -> None:
    # The default — must not raise even with Secure off (e.g. local HTTP dev).
    settings = Settings(
        refresh_cookie_enabled=True,
        refresh_cookie_samesite="lax",
        refresh_cookie_secure=False,
    )
    assert settings.refresh_cookie_samesite == "lax"
