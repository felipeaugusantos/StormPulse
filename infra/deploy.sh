#!/usr/bin/env bash
# StormPulse — safe production deploy sequence (hardening Fase 3, ADR-0044).
#
# Called remotely by .github/workflows/ci.yml's `deploy` job over SSH,
# after checkout to the exact validated commit (STORMPULSE_IMAGE/
# STORMPULSE_WEB_IMAGE/STORMPULSE_WORKER_IMAGE already exported). Can also
# be run by hand on the server for a manual redeploy — with those
# variables left unset, it falls back to whatever docker-compose.prod.yml
# resolves from .env.
#
# Order matters, and is the whole point of this script: Postgres/Redis up
# and healthy -> pre-deploy backup -> migration in a one-shot container
# (never inside a live-serving API) -> only then replace
# api/worker/beat/web -> wait for /ready -> functional smoke test. A
# failure at any point rolls back to the images that were running before
# this script started (recorded up front) instead of leaving a
# half-upgraded stack. Migrations are never auto-downgraded — that stays
# a human decision (see infra/README.md § Rollback).

set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

PREV_API_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-api-1 2>/dev/null || echo "")"
PREV_WEB_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-web-1 2>/dev/null || echo "")"
echo "Previous images (kept for rollback): api=${PREV_API_IMAGE:-<none, first deploy>} web=${PREV_WEB_IMAGE:-<none>}"

rollback() {
  trap - ERR # never recurse if rollback itself fails
  echo "!!! Deploy failed — dumping the last 200 log lines per service:"
  "${COMPOSE[@]}" logs --no-color --tail 200 || true
  if [ -n "$PREV_API_IMAGE" ]; then
    echo "==> Rolling back to the previous images: api=$PREV_API_IMAGE web=$PREV_WEB_IMAGE"
    STORMPULSE_IMAGE="$PREV_API_IMAGE" STORMPULSE_WEB_IMAGE="$PREV_WEB_IMAGE" \
      "${COMPOSE[@]}" up -d api worker beat web || echo "WARNING: rollback itself failed — manual intervention needed"
  else
    echo "No previous image recorded (first deploy on this server?) — nothing to roll back to."
  fi
  exit 1
}
trap rollback ERR

echo "==> Pulling images for this deploy"
"${COMPOSE[@]}" pull

echo "==> Ensuring Postgres/Redis are up and healthy"
"${COMPOSE[@]}" up -d db redis
timeout 60 bash -c '
  until [ "$(docker inspect --format="{{.State.Health.Status}}" stormpulse-db-1 2>/dev/null)" = healthy ] &&
        [ "$(docker inspect --format="{{.State.Health.Status}}" stormpulse-redis-1 2>/dev/null)" = healthy ]; do
    sleep 2
  done
'
echo "Postgres and Redis are healthy."

echo "==> Pre-deploy backup (best-effort — a failed backup must not block a deploy that fixes something urgent)"
POSTGRES_USER="${POSTGRES_USER:-stormpulse}" POSTGRES_DB="${POSTGRES_DB:-stormpulse}" \
  ./infra/backup-postgres.sh || echo "WARNING: pre-deploy backup failed, continuing anyway"

echo "==> Running migrations in a one-shot container — never inside the currently-serving API"
timeout 120 "${COMPOSE[@]}" run --rm api alembic upgrade head

echo "==> Migrations applied — updating api/worker/beat/web"
"${COMPOSE[@]}" up -d api worker beat web

echo "==> Waiting for /ready"
timeout 60 bash -c 'until curl -fsS http://localhost/ready 2>/dev/null | grep -q "\"status\":\"ready\""; do sleep 2; done'

echo "==> Functional smoke test"
curl -fsS http://localhost/health | grep -q '"status":"ok"'
curl -fsS http://localhost/api/v1/public/storms > /dev/null
"${COMPOSE[@]}" ps worker | grep -q "Up"
"${COMPOSE[@]}" ps beat | grep -q "Up"

trap - ERR
echo "==> Deploy confirmed."
docker image prune -f || true
