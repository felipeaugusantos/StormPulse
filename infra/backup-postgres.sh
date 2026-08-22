#!/usr/bin/env bash
# StormPulse — Postgres backup (hardening: infra de produção).
#
# Dumps the `db` service's database via `docker compose exec`, keeps the
# last $RETENTION_DAYS days locally. Run from the same directory as
# docker-compose.yml (crontab entry example in infra/README.md).
#
# Restore: see infra/README.md "Testando o restore" — this script only
# takes backups, it deliberately never restores anything automatically.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/stormpulse}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/stormpulse_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

docker compose "${COMPOSE_FILES[@]}" exec -T db \
    pg_dump -U "${POSTGRES_USER:-stormpulse}" -d "${POSTGRES_DB:-stormpulse}" \
    | gzip > "$OUT_FILE"

echo "Backup written to $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

# Prune anything older than RETENTION_DAYS — local disk only. For
# off-instance durability (surviving the EBS volume itself being lost),
# copy $OUT_FILE to S3 as a second step once an S3 bucket + IAM role are
# set up — deliberately not done automatically here (needs a decision
# about which bucket/credentials to use).
find "$BACKUP_DIR" -name 'stormpulse_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete
