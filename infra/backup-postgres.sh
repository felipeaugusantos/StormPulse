#!/usr/bin/env bash
# StormPulse — Postgres backup (hardening: infra de produção; mandatory-
# backup follow-up, ADR-0056).
#
# Dumps the `db` service's database via `docker compose exec`, keeps the
# last $RETENTION_DAYS days locally, optionally copies off-instance to S3.
# Run from the same directory as docker-compose.yml (crontab entry example
# in infra/README.md). infra/deploy.sh treats a nonzero exit here as a
# hard failure by default (ALLOW_DEPLOY_WITHOUT_BACKUP is the only escape
# hatch) — this script must never exit 0 with an unusable backup file.
#
# Restore: see infra/README.md "Testando o restore" — this script only
# takes backups, it deliberately never restores anything automatically.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/stormpulse}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RAW_FILE="${BACKUP_DIR}/stormpulse_${TIMESTAMP}.sql"
OUT_FILE="${RAW_FILE}.gz"

mkdir -p "$BACKUP_DIR"

# Dumped to a plain file first, not piped straight into gzip — a pipe's
# exit status tracking (PIPESTATUS) turned out to behave inconsistently
# across shells/environments during testing; writing pg_dump's own exit
# code straight into this `if` (a context `set -e` already always leaves
# alone) is simpler and doesn't depend on that at all.
#
# --exclude-schema=tiger/tiger_data/topology: PostGIS's own "tiger
# geocoder" extension schemas (addr, county, edges, ...) — the
# postgis/postgis image auto-creates these in every fresh database, so a
# plain dump/restore round-trip always collided with "schema already
# exists" restoring into any freshly-bootstrapped target (confirmed live
# testing the actual restore procedure, not assumed). Never application
# data, safe to exclude; they come back on their own from the image.
#
# --no-owner --no-privileges: without these, the dump embeds GRANT/ALTER
# OWNER statements naming the RLS runtime role (`stormpulse_app`, migration
# 0b7b9a5dbd11) — restoring into anything that hasn't already run that
# migration (a truly fresh Postgres, or a fresh disposable one for a
# restore drill) fails on "role stormpulse_app does not exist" (confirmed
# live). The role/RLS/grants are already fully reproducible by running
# migrations; a restore only needs the *data* back, then `alembic upgrade
# head` re-establishes ownership/RLS on top of it.
if ! docker compose "${COMPOSE_FILES[@]}" exec -T db \
  pg_dump -U "${POSTGRES_USER:-stormpulse}" -d "${POSTGRES_DB:-stormpulse}" \
  --exclude-schema=tiger --exclude-schema=tiger_data --exclude-schema=topology \
  --no-owner --no-privileges \
  >"$RAW_FILE"; then
  echo "ERROR: pg_dump failed." >&2
  rm -f "$RAW_FILE"
  exit 1
fi
if [ ! -s "$RAW_FILE" ]; then
  echo "ERROR: pg_dump produced an empty dump file." >&2
  rm -f "$RAW_FILE"
  exit 1
fi

if ! gzip -f "$RAW_FILE"; then
  echo "ERROR: failed to compress the dump." >&2
  rm -f "$RAW_FILE" "$OUT_FILE"
  exit 1
fi
if [ ! -s "$OUT_FILE" ] || ! gzip -t "$OUT_FILE" 2>/dev/null; then
  echo "ERROR: backup file $OUT_FILE is missing or not a valid gzip archive." >&2
  rm -f "$OUT_FILE"
  exit 1
fi

echo "Backup written to $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

# Optional off-instance copy to S3 — opt-in only (BACKUP_S3_BUCKET unset
# by default, so a plain dev/CI run never needs AWS anything). Credentials
# always come from the environment/instance IAM role, never a CLI flag —
# a flag would show up in `docker top`/process listings; this script also
# never echoes any AWS_* variable.
if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    echo "==> Uploading backup to s3://${BACKUP_S3_BUCKET}/$(basename "$OUT_FILE")"
    if aws s3 cp "$OUT_FILE" "s3://${BACKUP_S3_BUCKET}/$(basename "$OUT_FILE")" --only-show-errors; then
      echo "Uploaded to S3."
    else
      echo "WARNING: S3 upload failed — the local backup above is still valid and kept." >&2
    fi
  else
    echo "WARNING: BACKUP_S3_BUCKET is set but the 'aws' CLI isn't installed — skipped S3 upload." >&2
  fi
fi

# Prune anything older than RETENTION_DAYS — local disk only; the S3 copy
# above (if configured) is expected to have its own lifecycle rule on the
# bucket, not managed by this script.
find "$BACKUP_DIR" -name 'stormpulse_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete
