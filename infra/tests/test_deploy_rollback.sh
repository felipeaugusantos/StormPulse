#!/usr/bin/env bash
# Tests for infra/deploy.sh's rollback and mandatory-backup behavior
# (ADR-0056) — a stub `docker`/`curl` on PATH replaces every real call;
# this never touches a real Docker daemon, Postgres, or network. Each
# scenario copies deploy.sh into a throwaway "repo" so the real backup
# script (already covered by test_backup_postgres.sh) can be swapped for
# a trivial success/failure stub, isolating rollback-specific behavior
# from backup-specific behavior. Run: ./infra/tests/test_deploy_rollback.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
REPO_ROOT="$(pwd)"

FAILED=0
pass() { echo "PASS: $1"; }
fail() {
  echo "FAIL: $1"
  FAILED=1
}

# --- Build one throwaway "deploy repo" per scenario ------------------------
# Real docker-compose.yml/.prod.yml content is irrelevant to the stub
# `docker`, which never reads them — only their *presence* matters (`-f`
# arguments deploy.sh always passes along).
new_scenario_dir() {
  local dir
  dir="$(mktemp -d)"
  mkdir -p "$dir/infra/tls"
  cp "$REPO_ROOT/infra/deploy.sh" "$dir/infra/deploy.sh"
  touch "$dir/docker-compose.yml" "$dir/docker-compose.prod.yml"
  printf '#!/usr/bin/env bash\nexit %s\n' "${1:-0}" >"$dir/infra/backup-postgres.sh"
  chmod +x "$dir/infra/deploy.sh" "$dir/infra/backup-postgres.sh"
  echo "$dir"
}

# --- Stub `docker` --------------------------------------------------------
# Behavior entirely driven by env vars the test sets before invoking
# deploy.sh (STUB_* below) plus a per-scenario STATE_DIR it logs calls to.
write_docker_stub() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  cat >"$bin_dir/docker" <<'STUB'
#!/usr/bin/env bash
STATE_DIR="${STUB_STATE_DIR:?}"
echo "$*" >>"$STATE_DIR/docker.log"

if [ "$1" = "inspect" ]; then
  shift
  fmt="" target=""
  for a in "$@"; do
    case "$a" in
    --format=*) fmt="${a#--format=}" ;;
    *) target="$a" ;;
    esac
  done
  if [[ "$fmt" == *"Health.Status"* ]]; then
    echo "healthy"
    exit 0
  fi
  if [[ "$fmt" == *"Config.Image"* ]]; then
    case "$target" in
    stormpulse-api-1) echo "${STUB_PREV_API_IMAGE:-}" ;;
    stormpulse-web-1) echo "${STUB_PREV_WEB_IMAGE:-}" ;;
    stormpulse-worker-1) echo "${STUB_PREV_WORKER_IMAGE:-}" ;;
    stormpulse-beat-1) echo "${STUB_PREV_BEAT_IMAGE:-}" ;;
    *) echo "" ;;
    esac
    exit 0
  fi
  exit 0
fi

if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  img="$3"
  for missing in ${STUB_MISSING_IMAGES:-}; do
    [ "$img" = "$missing" ] && exit 1
  done
  exit 0
fi

if [ "$1" = "compose" ]; then
  shift
  # Skip the "-f <file>" pairs deploy.sh always passes.
  while [ "${1:-}" = "-f" ]; do
    shift 2
  done
  sub="${1:-}"
  shift || true
  case "$sub" in
  pull)
    [ "${STUB_FAIL_AT:-}" = "pull" ] && exit 1
    exit 0
    ;;
  up)
    # "$@" is now e.g. "-d db redis" or "-d api worker beat web".
    if [[ "$*" == *"db redis"* ]]; then
      [ "${STUB_FAIL_AT:-}" = "db_redis_up" ] && exit 1
      exit 0
    fi
    # api/worker/beat/web — first call is the real deploy, a second call
    # (if it happens) is rollback's own re-apply.
    count_file="$STATE_DIR/up_deploy_calls"
    count=$(($(cat "$count_file" 2>/dev/null || echo 0) + 1))
    echo "$count" >"$count_file"
    echo "STORMPULSE_WORKER_IMAGE=${STORMPULSE_WORKER_IMAGE:-}" >>"$STATE_DIR/up_calls_detail.log"
    if [ "$count" -eq 1 ]; then
      [ "${STUB_FAIL_AT:-}" = "deploy_up" ] && exit 1
      exit 0
    else
      [ "${STUB_FAIL_ROLLBACK_UP:-false}" = "true" ] && exit 1
      exit 0
    fi
    ;;
  run)
    # "--rm api alembic upgrade head"
    [ "${STUB_FAIL_AT:-}" = "migrate" ] && exit 1
    exit 0
    ;;
  ps)
    service="$1"
    for failed in ${STUB_FAIL_PS:-}; do
      [ "$service" = "$failed" ] && {
        echo "$service   Exit 1"
        exit 0
      }
    done
    echo "$service   Up 2 minutes"
    exit 0
    ;;
  logs)
    echo "(fake logs)"
    exit 0
    ;;
  exec)
    # Backup script's own pg_dump call — not exercised by these tests
    # (backup-postgres.sh is stubbed out per-scenario), but handled so a
    # stray call never hangs the test.
    exit 0
    ;;
  *)
    exit 0
    ;;
  esac
fi

if [ "$1" = "image" ] && [ "$2" = "prune" ]; then
  exit 0
fi

exit 0
STUB
  chmod +x "$bin_dir/docker"
}

# --- Stub `curl` -----------------------------------------------------------
# deploy.sh's curl_local tries https then http; always answer "ready"/"ok"
# immediately unless STUB_UNHEALTHY=true (used for the "rollback itself
# isn't healthy" scenario).
write_curl_stub() {
  local bin_dir="$1"
  cat >"$bin_dir/curl" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in
  *localhost/ready)
    if [ "${STUB_UNHEALTHY:-false}" = "true" ]; then
      exit 7
    fi
    echo '{"status":"ready"}'
    exit 0
    ;;
  *localhost/health)
    [ "${STUB_UNHEALTHY:-false}" = "true" ] && exit 7
    echo '{"status":"ok"}'
    exit 0
    ;;
  *localhost/api/v1/public/storms)
    [ "${STUB_UNHEALTHY:-false}" = "true" ] && exit 7
    echo '[]'
    exit 0
    ;;
  esac
done
exit 7
STUB
  chmod +x "$bin_dir/curl"
}

run_deploy() {
  local scenario_dir="$1"
  (cd "$scenario_dir" && ./infra/deploy.sh) >"$scenario_dir/deploy.log" 2>&1
}

# ============================================================================
# Scenario A: everything succeeds — no rollback should ever fire.
# ============================================================================
DIR="$(new_scenario_dir 0)"
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR"
BIN="$DIR/bin"
write_docker_stub "$BIN"
write_curl_stub "$BIN"
if PATH="$BIN:$PATH" STUB_STATE_DIR="$STATE_DIR" \
  STUB_PREV_API_IMAGE=api:old STUB_PREV_WEB_IMAGE=web:old \
  STUB_PREV_WORKER_IMAGE=worker:old STUB_PREV_BEAT_IMAGE=api:old \
  STORMPULSE_IMAGE=api:new STORMPULSE_WEB_IMAGE=web:new STORMPULSE_WORKER_IMAGE=worker:new \
  run_deploy "$DIR"; then
  pass "happy path: deploy.sh exits 0 when everything succeeds"
else
  fail "happy path: deploy.sh exited nonzero unexpectedly"
  cat "$DIR/deploy.log"
fi
if [ "$(cat "$STATE_DIR/up_deploy_calls" 2>/dev/null)" = "1" ]; then
  pass "happy path: api/worker/beat/web brought up exactly once (no rollback triggered)"
else
  fail "happy path: expected exactly 1 'up -d api worker beat web' call"
fi

# ============================================================================
# Scenario B: migration fails — rollback must restore ALL FOUR images
# independently, including worker/beat (the actual bug this fixes), and
# never inherit the failed deploy's STORMPULSE_WORKER_IMAGE.
# ============================================================================
DIR="$(new_scenario_dir 0)"
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR"
BIN="$DIR/bin"
write_docker_stub "$BIN"
write_curl_stub "$BIN"
PATH="$BIN:$PATH" STUB_STATE_DIR="$STATE_DIR" \
  STUB_FAIL_AT=migrate \
  STUB_PREV_API_IMAGE=api:old STUB_PREV_WEB_IMAGE=web:old \
  STUB_PREV_WORKER_IMAGE=worker:old STUB_PREV_BEAT_IMAGE=api:old \
  STORMPULSE_IMAGE=api:new STORMPULSE_WEB_IMAGE=web:new STORMPULSE_WORKER_IMAGE=worker:new-broken \
  run_deploy "$DIR"
RC=$?
if [ "$RC" -ne 0 ]; then
  pass "migration failure: deploy.sh exits nonzero"
else
  fail "migration failure: deploy.sh exited 0, expected failure"
fi
if grep -q "^STORMPULSE_WORKER_IMAGE=worker:old$" "$STATE_DIR/up_calls_detail.log" 2>/dev/null; then
  pass "rollback restores worker to its OWN previous image (worker:old), not the failed deploy's"
else
  fail "rollback did not restore worker:old — got: $(cat "$STATE_DIR/up_calls_detail.log" 2>/dev/null)"
fi
if ! grep -q "worker:new-broken" "$STATE_DIR/up_calls_detail.log" 2>/dev/null; then
  pass "rollback never re-applies the failed deploy's worker image"
else
  fail "rollback leaked the failed deploy's worker:new-broken image"
fi
if grep -q "Rollback confirmed healthy" "$DIR/deploy.log"; then
  pass "rollback verifies the rolled-back stack is healthy before declaring success"
else
  fail "rollback did not confirm health — log:"
  cat "$DIR/deploy.log"
fi

# ============================================================================
# Scenario C: a previous image is missing — rollback must abort cleanly
# with an unambiguous manual-intervention message, not attempt a partial
# rollback.
# ============================================================================
DIR="$(new_scenario_dir 0)"
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR"
BIN="$DIR/bin"
write_docker_stub "$BIN"
write_curl_stub "$BIN"
PATH="$BIN:$PATH" STUB_STATE_DIR="$STATE_DIR" \
  STUB_FAIL_AT=migrate \
  STUB_PREV_API_IMAGE=api:old STUB_PREV_WEB_IMAGE=web:old \
  STUB_PREV_WORKER_IMAGE=worker:old STUB_PREV_BEAT_IMAGE=api:old \
  STUB_MISSING_IMAGES="worker:old" \
  run_deploy "$DIR"
RC=$?
if [ "$RC" -ne 0 ] && grep -q "ROLLBACK ABORTED" "$DIR/deploy.log" && grep -qi "MANUAL INTERVENTION" "$DIR/deploy.log"; then
  pass "missing previous image: rollback aborts with a clear manual-intervention message"
else
  fail "missing previous image: expected a clear ROLLBACK ABORTED + MANUAL INTERVENTION message"
  cat "$DIR/deploy.log"
fi

# ============================================================================
# Scenario D: pre-deploy backup fails, ALLOW_DEPLOY_WITHOUT_BACKUP unset
# (default false) — deploy must abort BEFORE running migrations.
# ============================================================================
DIR="$(new_scenario_dir 1)" # backup-postgres.sh stub exits 1
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR"
BIN="$DIR/bin"
write_docker_stub "$BIN"
write_curl_stub "$BIN"
PATH="$BIN:$PATH" STUB_STATE_DIR="$STATE_DIR" \
  STUB_PREV_API_IMAGE=api:old \
  run_deploy "$DIR"
RC=$?
if [ "$RC" -ne 0 ]; then
  pass "backup failure (default): deploy.sh aborts"
else
  fail "backup failure (default): deploy.sh should have aborted"
fi
if grep -q "STUB_FAIL_AT.*migrate\|run --rm api alembic" "$STATE_DIR/docker.log" 2>/dev/null; then
  fail "backup failure (default): migration ran despite the backup failing"
else
  pass "backup failure (default): migration never ran"
fi

# ============================================================================
# Scenario E: pre-deploy backup fails, ALLOW_DEPLOY_WITHOUT_BACKUP=true —
# deploy proceeds, with a loud warning and an audit trail line.
# ============================================================================
DIR="$(new_scenario_dir 1)"
STATE_DIR="$DIR/state"
mkdir -p "$STATE_DIR"
BIN="$DIR/bin"
write_docker_stub "$BIN"
write_curl_stub "$BIN"
if PATH="$BIN:$PATH" STUB_STATE_DIR="$STATE_DIR" \
  STUB_PREV_API_IMAGE=api:old STUB_PREV_WEB_IMAGE=web:old \
  STUB_PREV_WORKER_IMAGE=worker:old STUB_PREV_BEAT_IMAGE=api:old \
  STORMPULSE_IMAGE=api:new STORMPULSE_WEB_IMAGE=web:new STORMPULSE_WORKER_IMAGE=worker:new \
  ALLOW_DEPLOY_WITHOUT_BACKUP=true \
  run_deploy "$DIR"; then
  pass "backup failure + ALLOW_DEPLOY_WITHOUT_BACKUP=true: deploy proceeds"
else
  fail "backup failure + ALLOW_DEPLOY_WITHOUT_BACKUP=true: deploy should have succeeded"
  cat "$DIR/deploy.log"
fi
if grep -qi "WARNING: PRE-DEPLOY BACKUP FAILED" "$DIR/deploy.log" && grep -q "^AUDIT " "$DIR/deploy.log"; then
  pass "backup override produces a loud warning and an AUDIT log line"
else
  fail "backup override did not produce the expected warning/audit line"
  cat "$DIR/deploy.log"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "All deploy.sh rollback/backup tests passed."
else
  echo "Some deploy.sh rollback/backup tests FAILED."
fi
exit "$FAILED"
