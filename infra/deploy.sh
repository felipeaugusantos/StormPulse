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

# Once TLS is set up (infra/setup-tls.sh, ADR-0039), port 80 redirects
# everything to HTTPS except the ACME challenge path — a plain `curl
# http://localhost/...` then just gets a 301 with no JSON body, which
# `curl -fsS` treats as a "success" (that flag only fails on 4xx/5xx), so
# a naive HTTP-only check silently never finds what it's grepping for.
# Try HTTPS first (self-signed-tolerant: the cert here is for the site's
# real hostname, not literally `localhost`), fall back to plain HTTP for
# a server that hasn't run setup-tls.sh yet.
curl_local() {
  local path="$1"
  curl -k -fsS "https://localhost${path}" 2>/dev/null || curl -fsS "http://localhost${path}" 2>/dev/null
}

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

echo "==> Refreshing infra/tls/nginx.conf.active from the tracked config (Fase 5, ADR-0046)"
# nginx.conf.active is generated once by infra/setup-tls.sh and is
# git-ignored (it bakes in the server's real domain) — without this step,
# any change to infra/tls/nginx-http.conf/nginx-https.conf in the repo
# would be built into new images but never actually reach the file Nginx
# has bind-mounted on this server, silently going stale deploy after
# deploy. Detects which mode is currently active from the file itself
# (HTTPS iff it has a "listen 443 ssl" server block) and re-derives the
# domain from its own server_name — never asks for it again.
if [ -f infra/tls/nginx.conf.active ] && grep -q "listen 443 ssl" infra/tls/nginx.conf.active; then
  DOMAIN="$(grep -m1 -oP '(?<=server_name )[^;]+' infra/tls/nginx.conf.active || true)"
  if [ -n "$DOMAIN" ]; then
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" infra/tls/nginx-https.conf > infra/tls/nginx.conf.active
    echo "Refreshed nginx.conf.active (HTTPS mode, domain=$DOMAIN)"
  else
    echo "WARNING: HTTPS mode detected but couldn't parse the domain out of the existing nginx.conf.active — leaving it untouched this deploy"
  fi
elif [ -f infra/tls/nginx.conf.active ]; then
  cp infra/tls/nginx-http.conf infra/tls/nginx.conf.active
  echo "Refreshed nginx.conf.active (HTTP-only mode — no certificate yet)"
else
  echo "No nginx.conf.active yet on this server — run infra/setup-tls.sh first."
fi

echo "==> Migrations applied — updating api/worker/beat/web"
"${COMPOSE[@]}" up -d api worker beat web

echo "==> Waiting for /ready"
export -f curl_local
timeout 60 bash -c 'until curl_local /ready | grep -q "\"status\":\"ready\""; do sleep 2; done'

echo "==> Functional smoke test"
curl_local /health | grep -q '"status":"ok"'
curl_local /api/v1/public/storms > /dev/null
"${COMPOSE[@]}" ps worker | grep -q "Up"
"${COMPOSE[@]}" ps beat | grep -q "Up"

trap - ERR
echo "==> Deploy confirmed."
docker image prune -f || true
