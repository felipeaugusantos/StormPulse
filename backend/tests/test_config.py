"""Tests for settings and derived connection URLs."""

from __future__ import annotations

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
