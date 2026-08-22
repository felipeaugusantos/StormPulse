#!/usr/bin/env python3
"""Verifies every service that needs `Settings` actually receives it via
`docker compose config` — hardening: env var passthrough audit (see the
commit that added this file for the bug it caught: TRUSTED_PROXY_IPS,
REFRESH_COOKIE_*, OTEL_*, INMET_*/CPTEC_*/OPEN_METEO_*/AGRO_* and
SATELLITE_EXTENT never reached any container before `env_file` replaced
the old hand-enumerated `${VAR:-default}` list).

Writes a temporary sentinel `.env` (backing up and restoring any real one
— never touches real secrets), runs `docker compose config --format json`
for both the dev compose file alone and the prod overlay, and asserts the
sentinel values appear in api/worker/beat's environment and do NOT leak
into db/redis (which don't need `Settings` at all).

Usage: `python infra/verify_compose_env.py` (run from anywhere — resolves
paths relative to this file, not the CWD).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
BACKUP_PATH = ROOT / ".env.verify-backup"
ACTIVE_NGINX = ROOT / "infra" / "tls" / "nginx.conf.active"

SENTINEL_ENV = """\
ENVIRONMENT=production
JWT_SECRET_KEY=sentinel-jwt-000000000000000000000000000000000000
POSTGRES_PASSWORD=sentinel-pg-000
TRUSTED_PROXY_IPS=203.0.113.55
REFRESH_COOKIE_ENABLED=true
REFRESH_COOKIE_NAME=sentinel_cookie_name
REFRESH_COOKIE_PATH=/sentinel/path
REFRESH_COOKIE_SECURE=true
REFRESH_COOKIE_SAMESITE=strict
REFRESH_COOKIE_DOMAIN=sentinel.example.com
OTEL_ENABLED=true
OTEL_SERVICE_NAME=sentinel-otel-service
OTEL_EXPORTER_OTLP_ENDPOINT=http://sentinel-otel-collector:4318
INMET_BASE_URL=https://sentinel-inmet.example
CPTEC_BASE_URL=https://sentinel-cptec.example
OPEN_METEO_FORECAST_URL=https://sentinel-open-meteo.example
AGRO_FROST_THRESHOLD_C=1.234
SATELLITE_EXTENT=-1.0,-2.0,-3.0,-4.0
"""

# (env var name, expected value as `docker compose config --format json`
# renders it — booleans/numbers come back as plain strings either way).
EXPECTED = [
    ("TRUSTED_PROXY_IPS", "203.0.113.55"),
    ("REFRESH_COOKIE_ENABLED", "true"),
    ("REFRESH_COOKIE_DOMAIN", "sentinel.example.com"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://sentinel-otel-collector:4318"),
    ("INMET_BASE_URL", "https://sentinel-inmet.example"),
    ("AGRO_FROST_THRESHOLD_C", "1.234"),
    ("SATELLITE_EXTENT", "-1.0,-2.0,-3.0,-4.0"),
]

SETTINGS_SERVICES = ("api", "worker", "beat")
NON_SETTINGS_SERVICES = ("db", "redis")


def run_compose_config(*extra_files: str) -> dict:
    cmd = ["docker", "compose"]
    for f in extra_files:
        cmd += ["-f", f]
    cmd += ["config", "--format", "json"]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def check(config: dict, label: str) -> list[str]:
    failures = []
    services = config.get("services", {})
    for service in SETTINGS_SERVICES:
        env = services.get(service, {}).get("environment", {})
        for key, expected in EXPECTED:
            actual = env.get(key)
            if str(actual) != expected:
                failures.append(
                    f"[{label}] {service}.{key} = {actual!r}, esperado {expected!r}"
                )
    for service in NON_SETTINGS_SERVICES:
        env = services.get(service, {}).get("environment", {})
        for key, _ in EXPECTED:
            if key in env:
                failures.append(
                    f"[{label}] {service}.{key} nao deveria estar presente (vazou pro banco/cache)"
                )
    return failures


def main() -> int:
    had_env = ENV_PATH.exists()
    if had_env:
        shutil.copy(ENV_PATH, BACKUP_PATH)
    had_active_nginx = ACTIVE_NGINX.exists()
    try:
        ENV_PATH.write_text(SENTINEL_ENV, encoding="utf-8")
        if not had_active_nginx:
            shutil.copy(ROOT / "infra" / "tls" / "nginx-http.conf", ACTIVE_NGINX)

        all_failures: list[str] = []
        all_failures += check(run_compose_config("docker-compose.yml"), "dev")
        all_failures += check(
            run_compose_config("docker-compose.yml", "docker-compose.prod.yml"), "prod"
        )

        if all_failures:
            print("FALHA na verificacao de passagem de variaveis:\n")
            for f in all_failures:
                print(f"  - {f}")
            return 1
        print(
            "OK: todas as variaveis sentinela chegaram aos servicos esperados "
            "(api/worker/beat) e nenhuma vazou pra db/redis."
        )
        return 0
    finally:
        if had_env:
            shutil.move(str(BACKUP_PATH), str(ENV_PATH))
        else:
            ENV_PATH.unlink(missing_ok=True)
        if not had_active_nginx:
            ACTIVE_NGINX.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
