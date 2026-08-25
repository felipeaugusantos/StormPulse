"""Tests for settings and derived connection URLs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_url_uses_asyncpg_driver() -> None:
    # database_url (the API's runtime connection, FASE 34/RLS) is built
    # from postgres_app_*, not the migration superuser's postgres_*.
    settings = Settings(
        postgres_host="db",
        postgres_port=5432,
        postgres_app_user="u",
        postgres_app_password="p",
        postgres_db="stormpulse",
    )
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/stormpulse"


def test_sync_database_url_uses_psycopg2_driver() -> None:
    settings = Settings(postgres_host="db", postgres_app_user="u", postgres_app_password="p")
    assert settings.sync_database_url.startswith("postgresql+psycopg2://")


def test_migration_database_url_uses_the_superuser_role() -> None:
    # Alembic must keep connecting as the bootstrap/superuser role — it's
    # the only one allowed to CREATE ROLE/GRANT (migration 0b7b9a5dbd11).
    settings = Settings(postgres_host="db", postgres_user="super", postgres_password="p")
    assert settings.migration_database_url == "postgresql+psycopg2://super:p@db:5432/stormpulse"


def test_redis_url_is_built_from_parts() -> None:
    settings = Settings(redis_host="cache", redis_port=6379, redis_db=1)
    assert settings.redis_url == "redis://cache:6379/1"


def test_production_refuses_the_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="production", jwt_secret_key="dev-insecure-change-me")


def test_production_refuses_the_dev_app_db_password() -> None:
    with pytest.raises(ValidationError, match="POSTGRES_APP_PASSWORD"):
        Settings(
            environment="production",
            jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
            postgres_app_password="stormpulse_app",
        )


def test_production_refuses_the_dev_field_encryption_keys() -> None:
    with pytest.raises(ValidationError, match="FIELD_ENCRYPTION_KEY"):
        Settings(
            environment="production",
            jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
            postgres_app_password="a-strong-production-db-password",
        )


def test_production_requires_secure_cookie_when_cookie_enabled() -> None:
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            environment="production",
            jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
            postgres_app_password="a-strong-production-db-password",
            field_encryption_key="dGhpcy1pcy1hLXN0cm9uZy1wcm9kLWtleS0zMmJieXRlcyE=",
            field_encryption_index_key="YW5vdGhlci1zdHJvbmctcHJvZC1pbmRleC1rZXktMzJiIQ==",
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
