"""Tests for settings and derived connection URLs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_database_url_uses_asyncpg_driver() -> None:
    # database_url (the API's runtime connection, FASE 34/RLS) is built
    # from postgres_app_* (fixed role name, configurable password), not
    # the migration superuser's postgres_*.
    settings = Settings(
        postgres_host="db",
        postgres_port=5432,
        postgres_app_password="p",
        postgres_db="stormpulse",
    )
    assert settings.database_url == "postgresql+asyncpg://stormpulse_app:p@db:5432/stormpulse"


def test_sync_database_url_uses_psycopg2_driver() -> None:
    settings = Settings(postgres_host="db", postgres_app_password="p")
    assert settings.sync_database_url.startswith("postgresql+psycopg2://")


def test_postgres_app_user_is_not_configurable() -> None:
    # POSTGRES_APP_USER used to be a settable field the RLS migration
    # (0b7b9a5dbd11) never actually read — setting it to anything else
    # silently broke the deployment. Passing it as a constructor kwarg is
    # now a no-op (Settings' `extra="ignore"`); the name always resolves
    # to POSTGRES_APP_ROLE regardless.
    settings = Settings(postgres_app_user="something-else", postgres_app_password="p")
    assert settings.postgres_app_user == "stormpulse_app"


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


def test_production_refuses_refresh_cookie_disabled() -> None:
    # The web dashboard's XSS blast-radius protection (ADR-0045) only
    # holds if REFRESH_COOKIE_ENABLED is actually on — an incomplete .env
    # silently falling back to the code default (False) must fail loudly
    # in production, not ship the refresh token in the JSON body/localStorage.
    with pytest.raises(ValidationError, match="REFRESH_COOKIE_ENABLED"):
        Settings(
            environment="production",
            jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
            postgres_app_password="a-strong-production-db-password",
            field_encryption_key="dGhpcy1pcy1hLXN0cm9uZy1wcm9kLWtleS0zMmJieXRlcyE=",
            field_encryption_index_key="YW5vdGhlci1zdHJvbmctcHJvZC1pbmRleC1rZXktMzJiIQ==",
            refresh_cookie_enabled=False,
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


def _valid_production_settings(*, weather_provider: str) -> Settings:
    """A from-scratch, fully-valid production `Settings` (every other
    production-only check satisfied) except for the caller's own choice of
    `weather_provider` — isolates exactly what the two tests below check."""
    return Settings(
        environment="production",
        jwt_secret_key="a-strong-production-secret-at-least-32-bytes!",
        postgres_app_password="a-strong-production-db-password",
        field_encryption_key="dGhpcy1pcy1hLXN0cm9uZy1wcm9kLWtleS0zMmJieXRlcyE=",
        field_encryption_index_key="YW5vdGhlci1zdHJvbmctcHJvZC1pbmRleC1rZXktMzJiIQ==",
        refresh_cookie_enabled=True,
        refresh_cookie_secure=True,
        weather_provider=weather_provider,
    )


def test_production_refuses_mock_weather_provider() -> None:
    with pytest.raises(ValidationError, match="WEATHER_PROVIDER"):
        _valid_production_settings(weather_provider="mock")


def test_production_accepts_a_real_weather_provider() -> None:
    # Positive case — a fully-valid production config (every other
    # production-only check satisfied) with a real provider must not raise.
    settings = _valid_production_settings(weather_provider="inmet")
    assert settings.weather_provider == "inmet"


def test_non_production_still_defaults_to_mock() -> None:
    # The dev/test/CI convenience default — must stay untouched outside
    # production (every test in this suite implicitly relies on this).
    settings = Settings()
    assert settings.weather_provider == "mock"


def test_blank_optional_secret_env_vars_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` ships every optional secret as a *present but empty*
    line (`HCAPTCHA_SECRET_KEY=`, `VAPID_PRIVATE_KEY=`, ...) — confirmed
    live (item 8/FASE 8) that a plain `cp .env.example .env` left these as
    `SecretStr('')`, not `None`, silently making `verify_captcha` (and the
    same-shaped VAPID/INMET/etc. checks) treat an unconfigured feature as
    configured with an empty credential."""
    monkeypatch.setenv("HCAPTCHA_SECRET_KEY", "")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    settings = Settings(environment="test")
    assert settings.hcaptcha_secret_key is None
    assert settings.vapid_private_key is None
    assert settings.google_client_id is None


def test_non_blank_optional_secret_env_vars_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HCAPTCHA_SECRET_KEY", "a-real-secret")
    settings = Settings(environment="test")
    assert settings.hcaptcha_secret_key is not None
    assert settings.hcaptcha_secret_key.get_secret_value() == "a-real-secret"
