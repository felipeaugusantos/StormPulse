"""Central application configuration (12-factor: everything via env)."""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Literal

from pydantic import (
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    computed_field,
    model_validator,
)
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

    # --- Rate limiting (all versioned API endpoints, FASE 14) ---
    default_rate_limit_max: int = Field(default=120, gt=0)
    default_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # --- Rate limiting (public/visitor endpoints, FASE 15 — stricter: anonymous) ---
    public_rate_limit_max: int = Field(default=30, gt=0)
    public_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # --- Rate limiting: trusted proxy policy (hardening ADR-0033) ---
    # Empty by default — fail-safe-closed. With no trusted proxy configured,
    # `Forwarded`/`X-Forwarded-For` are never trusted and the limiter always
    # keys on the direct TCP peer, which is correct with no reverse proxy in
    # front (local dev, the current deploy). Only set this to the reverse
    # proxy's own IP(s)/CIDR(s) once one is actually in front of the API —
    # trusting it blindly here would let any client spoof these headers to
    # either dodge the limit or frame another IP for it.
    trusted_proxy_ips: str = ""

    # --- Observability / tracing (FASE 14) ---
    otel_enabled: bool = True
    otel_service_name: str = "stormpulse-backend"
    otel_exporter_otlp_endpoint: str | None = None

    # --- CORS (dashboard web / app mobile) ---
    cors_allowed_origins: str = "http://localhost:5173"

    # --- Refresh token cookie (hardening ADR-0029) — opt-in, off by
    # default. Migrating the refresh token from the JS-readable response
    # body to an HttpOnly cookie needs a real production domain topology
    # decided first (same-origin vs. cross-site changes SameSite/CSRF
    # requirements) — not decided yet, so this stays disabled until then.
    # With it off, every endpoint behaves exactly as before this ADR.
    refresh_cookie_enabled: bool = False
    refresh_cookie_name: str = "stormpulse_refresh"
    # Cookie's own explicit path — the browser never sends it on any other
    # route, limiting exposure if another endpoint were ever compromised.
    refresh_cookie_path: str = "/api/v1/auth"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: Literal["strict", "lax", "none"] = "lax"
    # None = host-only cookie (no Domain attribute) — correct for a
    # same-origin deploy. Only set this once a real domain exists.
    refresh_cookie_domain: str | None = None

    # --- Google OAuth (login social) ---
    # Only the client_id is needed: verifying an ID token's signature +
    # audience doesn't require the client secret (that's only for the
    # server-side authorization-code exchange flow, which we don't use).
    google_client_id: str | None = None

    # --- Platform admin bootstrap (FASE 28, ADR-0048) ---
    # On every API startup, if set and a User with this email already
    # exists, it's promoted to a cross-tenant platform operator
    # (is_platform_admin=True) — idempotent, safe to leave set permanently.
    # Never creates the account itself; the email must already be
    # registered (e.g. via normal signup) before it can be promoted.
    # Plain `str`, not `EmailStr` — an unset/empty ".env" value (the
    # documented default) must not fail Settings validation the way an
    # empty `EmailStr` would; malformed values simply never match a real
    # user, which is a harmless no-op, not worth hard-failing startup over.
    platform_admin_email: str | None = None

    # --- Weather source (FASE 5) ---
    weather_provider: str = "mock"

    # --- INMET real provider (FASE 13) ---
    inmet_base_url: str = "https://apitempo.inmet.gov.br"
    inmet_avisos_url: str = "https://apiprevmet3.inmet.gov.br"
    inmet_previsao_url: str = "https://apiprevmet3.inmet.gov.br"
    ibge_localidades_url: str = "https://servicodados.ibge.gov.br/api/v1/localidades"
    inmet_api_token: SecretStr | None = None
    inmet_http_timeout_seconds: float = Field(default=10.0, gt=0)
    inmet_min_rain_rate_mm_h: float = Field(default=4.0, gt=0)
    inmet_max_station_distance_km: float = Field(default=100.0, gt=0)

    # --- Satellite observation (GOES-19 / TATHU, FASE 16) ---
    # Off by default: real infra cost (GDAL, ~20-30MB NetCDF per band per
    # 10-min cycle) — opt in explicitly.
    satellite_enabled: bool = False
    satellite_stac_url: str = "https://data.inpe.br/bdc/stac/v1"
    satellite_collection: str = "GOES19-L2-CMI-1"
    satellite_band: str = "B13"
    # Brazil bounding box: lon_min,lat_min,lon_max,lat_max.
    satellite_extent: str = "-74,-34,-34,6"
    satellite_threshold_kelvin: float = Field(default=230.0, gt=0)
    satellite_min_area_km2: float = Field(default=3000.0, gt=0)
    satellite_grid_resolution_km: float = Field(default=4.0, gt=0)
    satellite_max_watch_age_hours: float = Field(default=3.0, gt=0)

    # --- Raios / descargas atmosféricas (API-REDEMET STSC, FASE 23) ---
    # Off by default — precisa de cadastro/chave (ver ADR-0019). Sinal mais
    # direto de convecção ativa que temos: diferente de StormCell (taxa de
    # chuva) e ConvectiveWatch (topo de nuvem fria via satélite), é detecção
    # real de descarga, não uma proxy indireta.
    lightning_enabled: bool = False
    redemet_api_key: SecretStr | None = None
    redemet_base_url: str = "https://api-redemet.decea.mil.br"
    lightning_http_timeout_seconds: float = Field(default=15.0, gt=0)
    # Quanto tempo um raio detectado continua aparecendo no mapa antes de
    # ser considerado obsoleto e removido — é um instantâneo do "agora", não
    # um histórico permanente (mesmo espírito do SatelliteImage).
    lightning_retention_minutes: float = Field(default=30.0, gt=0)

    # --- INPE/CPTEC forecast (redundância, FASE 17) ---
    # Serviço XML público do CPTEC — sem chave, sem geocódigo (aceita
    # lat/lon direto). Usado como fallback automático de `get_current_data`
    # e `get_forecast` quando o provedor primário (INMET) falha; ligado por
    # padrão porque o custo é baixo (só uma chamada HTTP extra, só quando o
    # primário já falhou) — ao contrário do satélite, que sempre baixa e
    # processa NetCDF.
    cptec_base_url: str = "https://servicos.cptec.inpe.br/XML"
    cptec_http_timeout_seconds: float = Field(default=10.0, gt=0)
    cptec_fallback_enabled: bool = True

    # --- Open-Meteo (redundância, FASE 20) ---
    # Terceiro nível de fallback, atrás de INMET e CPTEC — agregador
    # internacional sem chave (ver ADR-0015). Único dos 3 que dá previsão
    # numérica de chuva de verdade (probabilidade + mm), não só
    # texto/código. Gratuito até 10.000 chamadas/dia para uso não
    # comercial — StormPulse fica bem abaixo disso.
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_http_timeout_seconds: float = Field(default=10.0, gt=0)
    open_meteo_fallback_enabled: bool = True

    # --- Sinais agronômicos (FASE 19) ---
    # Reusa get_forecast/get_recent_rainfall/get_current_data já existentes
    # — sem custo de infra novo (ao contrário do satélite), ligado por
    # padrão. Limiares são referências agronômicas genéricas, não
    # específicas por cultura — ver ADR-0014.
    agro_enabled: bool = True
    agro_frost_threshold_c: float = 3.0
    # Lighter, earlier-warning tier — see ADR-0018 (Agritempo comparison).
    # Any day at/below this (but above the severe threshold) is reported as
    # "risco leve", never silently merged into the severe warning.
    agro_frost_light_threshold_c: float = 6.0
    # 30, not 15: the dry-streak count can never exceed how many days of
    # rainfall history we fetch, so a real drought longer than the window
    # would otherwise show the exact same day count forever once it caught
    # up to the window size — misleading, since the alert reads as "still
    # 15 days" when it's really been 20+. 30 balances that against INMET's
    # one-HTTP-request-per-day cost for this lookup (no batch endpoint).
    agro_dry_spell_window_days: int = Field(default=30, gt=0)
    agro_dry_spell_min_days: int = Field(default=7, gt=0)
    agro_dry_spell_rain_threshold_mm: float = Field(default=1.0, ge=0)
    agro_spray_max_wind_kmh: float = Field(default=15.0, gt=0)
    # Only weighed in when a forecast with real precipitation_probability is
    # available (Open-Meteo, FASE 20) — INMET/CPTEC leave it unset, so this
    # simply doesn't disqualify the window when the source can't say.
    agro_spray_max_rain_probability_percent: int = Field(default=30, ge=0, le=100)
    # Thermal-inversion signature (ADR-0018): calm wind + high humidity,
    # classic at dawn — spray drifts instead of settling on the crop. Only
    # weighed in when the active source reports humidity (Open-Meteo/INMET;
    # CPTEC never gives current conditions at all).
    agro_spray_inversion_max_wind_kmh: float = Field(default=3.0, ge=0)
    agro_spray_inversion_min_humidity_percent: float = Field(default=90.0, ge=0, le=100)

    # --- NDVI por talhão (Copernicus Sentinel Hub, FASE 29) ---
    # Desligado por padrão — igual ao satélite (ADR-0053): exige
    # credenciais próprias (client_id/secret OAuth2 da Copernicus Data
    # Space Ecosystem) e consome cota mensal compartilhada da conta. Só se
    # aplica a talhões (locations com parent_location_id e boundary_geojson
    # preenchidos) — uma fazenda-ponto não tem polígono pra calcular NDVI
    # sobre. Revisita do Sentinel-2 é ~5 dias — não adianta consultar com
    # mais frequência que isso.
    ndvi_enabled: bool = False
    ndvi_sh_client_id: str | None = None
    ndvi_sh_client_secret: SecretStr | None = None
    ndvi_sh_token_url: str = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    ndvi_sh_statistics_url: str = "https://sh.dataspace.copernicus.eu/statistics/v1"
    ndvi_lookback_days: float = Field(default=15.0, gt=0)
    ndvi_http_timeout_seconds: float = Field(default=30.0, gt=0)

    # --- Notificação push real (Web Push / VAPID, FASE 22) ---
    # Sem serviço externo (FCM/APNs) — o navegador é o próprio serviço de
    # push, só a assinatura VAPID é local. `vapid_private_key`/
    # `vapid_public_key` são um par de chave EC P-256 crua, codificada em
    # base64url (gerar com `py_vapid`) — ver ADR-0016 e `.env.example` para
    # o passo a passo. Sem chave configurada, a task de entrega marca cada
    # notificação como `SUPPRESSED` em vez de tentar enviar (honesto, sem
    # fingir sucesso — mesmo espírito de `WeatherProviderUnavailableError`).
    vapid_private_key: SecretStr | None = None
    vapid_public_key: str | None = None
    vapid_subject: str = "mailto:contato@stormpulse.example"

    @model_validator(mode="after")
    def _forbid_dev_secret_in_production(self) -> Settings:
        if self.environment == "production" and (
            self.jwt_secret_key.get_secret_value() == _DEV_JWT_SECRET
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong secret in production "
                "(the built-in development secret is refused)."
            )
        if (
            self.environment == "production"
            and self.refresh_cookie_enabled
            and not self.refresh_cookie_secure
        ):
            raise ValueError(
                "REFRESH_COOKIE_SECURE must be true in production (a "
                "non-Secure cookie would be sent over plain HTTP)."
            )
        # Not just a production concern — every modern browser rejects a
        # `SameSite=None` cookie outright unless `Secure` is also set,
        # regardless of environment. Fail at startup rather than silently
        # shipping a cookie no browser will ever actually store.
        if (
            self.refresh_cookie_enabled
            and self.refresh_cookie_samesite == "none"
            and not self.refresh_cookie_secure
        ):
            raise ValueError(
                "REFRESH_COOKIE_SAMESITE=none requires REFRESH_COOKIE_SECURE=true "
                "(browsers reject SameSite=None cookies that aren't Secure)."
            )
        # A misconfiguration here must fail loudly at startup, never fall
        # back to serving mock NDVI values silently under NDVI_ENABLED=true
        # — that would look like a real reading to anyone consuming it.
        if self.ndvi_enabled and not (self.ndvi_sh_client_id and self.ndvi_sh_client_secret):
            raise ValueError(
                "NDVI_ENABLED=true requires NDVI_SH_CLIENT_ID and NDVI_SH_CLIENT_SECRET to be set."
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
    def cors_allowed_origins_list(self) -> list[str]:
        """Parsed from a comma-separated env var (12-factor friendly)."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        """Parsed from a comma-separated env var of IPs/CIDRs (12-factor friendly)."""
        return [
            ipaddress.ip_network(entry.strip(), strict=False)
            for entry in self.trusted_proxy_ips.split(",")
            if entry.strip()
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def satellite_extent_bbox(self) -> tuple[float, float, float, float]:
        """``(lon_min, lat_min, lon_max, lat_max)`` parsed from the env string."""
        parts = [float(p.strip()) for p in self.satellite_extent.split(",")]
        if len(parts) != 4:
            raise ValueError(
                f"satellite_extent must have 4 comma-separated values: {self.satellite_extent!r}"
            )
        return parts[0], parts[1], parts[2], parts[3]

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
