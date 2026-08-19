"""Central application configuration (12-factor: everything via env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# Sentinel dev secret. Refused in production (see the validator below).
_DEV_JWT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    """Application settings.

    Values are read from environment variables (and a local ``.env`` during
    development). Secrets must never be hard-coded — see ``.env.example``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_name: str = "StormPulse"
    environment: Environment = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- Database (PostgreSQL + PostGIS) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "stormpulse"
    postgres_password: str = "stormpulse"
    postgres_db: str = "stormpulse"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- Readiness probe ---
    readiness_timeout_seconds: float = Field(default=2.0, gt=0)

    # --- Security / JWT (FASE 3) ---
    jwt_secret_key: SecretStr = Field(default=SecretStr(_DEV_JWT_SECRET))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=7, gt=0)

    # --- Rate limiting (auth endpoints) ---
    auth_rate_limit_max: int = Field(default=10, gt=0)
    auth_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # --- Weather source (FASE 5) ---
    weather_provider: str = "mock"

    @model_validator(mode="after")
    def _forbid_dev_secret_in_production(self) -> Settings:
        if self.environment == "production" and (
            self.jwt_secret_key.get_secret_value() == _DEV_JWT_SECRET
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong secret in production "
                "(the built-in development secret is refused)."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (asyncpg driver)."""
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Sync URL used by Alembic migrations (psycopg/psycopg2 style)."""
        dsn = PostgresDsn.build(
            scheme="postgresql+psycopg2",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        dsn = RedisDsn.build(
            scheme="redis",
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )
        return str(dsn)


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
