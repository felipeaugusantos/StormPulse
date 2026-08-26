#!/usr/bin/env bash
# Tests for infra/backup-postgres.sh (hardening ADR-0056) — a stub `docker`
# on PATH replaces `docker compose exec -T db pg_dump`, so this never
# touches a real Postgres or Docker daemon. Run: ./infra/tests/test_backup_postgres.sh
set -euo pipefail
cd "$(dirname "$0")/../.." || exit 1

FAILED=0
pass() { echo "PASS: $1"; }
fail() {
  echo "FAIL: $1"
  FAILED=1
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/bin"
cat >"$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
# Only ever called here as: docker compose ... exec -T db pg_dump ...
if [ "${STUB_PG_DUMP_FAIL:-false}" = "true" ]; then
  echo "stub pg_dump: simulated failure" >&2
  exit 1
fi
echo "-- fake pg_dump output --"
echo "CREATE TABLE fake (id int);"
STUB
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"

# --- Scenario 1: successful backup creates a valid, non-empty file ---
BACKUP_DIR="$WORK/backups1"
if BACKUP_DIR="$BACKUP_DIR" RETENTION_DAYS=14 ./infra/backup-postgres.sh >"$WORK/out1.log" 2>&1; then
  FILE="$(find "$BACKUP_DIR" -name 'stormpulse_*.sql.gz' | head -1)"
  if [ -n "$FILE" ] && [ -s "$FILE" ] && gzip -t "$FILE" 2>/dev/null; then
    pass "successful backup produces a non-empty, valid gzip file"
  else
    fail "successful backup did not produce a valid non-empty file (got: ${FILE:-<none>})"
  fi
else
  fail "backup-postgres.sh exited nonzero on the happy path"
  cat "$WORK/out1.log"
fi

# --- Scenario 2: pg_dump failure must make the script exit nonzero ---
BACKUP_DIR="$WORK/backups2"
if STUB_PG_DUMP_FAIL=true BACKUP_DIR="$BACKUP_DIR" ./infra/backup-postgres.sh >"$WORK/out2.log" 2>&1; then
  fail "backup-postgres.sh exited 0 despite pg_dump failing (pipefail should have caught this)"
else
  pass "pg_dump failure makes backup-postgres.sh exit nonzero"
fi
if find "$BACKUP_DIR" -name 'stormpulse_*.sql.gz' -size +0c 2>/dev/null | grep -q .; then
  fail "a non-empty backup file was left behind despite pg_dump failing"
else
  pass "no non-empty backup file left behind after a failed pg_dump"
fi

# --- Scenario 3: retention actually prunes old backups ---
BACKUP_DIR="$WORK/backups3"
mkdir -p "$BACKUP_DIR"
OLD_FILE="$BACKUP_DIR/stormpulse_20200101T000000Z.sql.gz"
echo "old" | gzip >"$OLD_FILE"
touch -d '30 days ago' "$OLD_FILE" 2>/dev/null || touch -t 202001010000 "$OLD_FILE"
BACKUP_DIR="$BACKUP_DIR" RETENTION_DAYS=14 ./infra/backup-postgres.sh >"$WORK/out3.log" 2>&1
if [ -f "$OLD_FILE" ]; then
  fail "retention did not prune a backup older than RETENTION_DAYS"
else
  pass "retention prunes backups older than RETENTION_DAYS"
fi

if [ "$FAILED" -eq 0 ]; then
  echo "All backup-postgres.sh tests passed."
else
  echo "Some backup-postgres.sh tests FAILED."
fi
exit "$FAILED"
