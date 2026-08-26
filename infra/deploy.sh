#!/usr/bin/env bash
# StormPulse — safe production deploy sequence (hardening Fase 3, ADR-0044;
# rollback/backup hardening follow-up, ADR-0056).
#
# Called remotely by .github/workflows/ci.yml's `deploy` job over SSH,
# after checkout to the exact validated commit (STORMPULSE_IMAGE/
# STORMPULSE_WEB_IMAGE/STORMPULSE_WORKER_IMAGE already exported). Can also
# be run by hand on the server for a manual redeploy — with those
# variables left unset, it falls back to whatever docker-compose.prod.yml
# resolves from .env, which this script itself keeps pointed at the last
# successfully deployed images (see the end of the script) — never the
# hardcoded `:latest` in docker-compose.prod.yml, which nothing on this
# branch ever actually publishes to.
#
# Order matters, and is the whole point of this script: Postgres/Redis up
# and healthy -> pre-deploy backup (mandatory by default, see
# ALLOW_DEPLOY_WITHOUT_BACKUP below) -> migration in a one-shot container
# (never inside a live-serving API) -> only then replace
# api/worker/beat/web -> wait for /ready -> functional smoke test. A
# failure at any point rolls back EVERY service (api/web/worker/beat,
# independently — see ADR-0056) to the images that were running before
# this script started (recorded up front), then verifies the rolled-back
# stack is actually healthy before declaring the rollback itself a
# success. Migrations are NEVER auto-downgraded — that stays a human
# decision (see infra/README.md § Rollback).

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
# Exported immediately (not just before the main "wait for /ready" step)
# — rollback() can fire well before that point (e.g. `docker compose pull`
# itself failing) and calls wait_for_ready too, which needs curl_local
# visible inside its own `bash -c` subshell from the very first line of
# this script that could possibly trigger a rollback.
export -f curl_local

# Shared between the main deploy path and rollback()'s own post-rollback
# check — a rollback that "succeeds" at `docker compose up -d` but leaves
# an unhealthy stack is not actually a successful rollback.
wait_for_ready() {
  timeout 60 bash -c 'until curl_local /ready | grep -q "\"status\":\"ready\""; do sleep 2; done'
}

verify_stack_healthy() {
  curl_local /health | grep -q '"status":"ok"' &&
    curl_local /api/v1/public/storms >/dev/null &&
    "${COMPOSE[@]}" ps api | grep -q "Up" &&
    "${COMPOSE[@]}" ps worker | grep -q "Up" &&
    "${COMPOSE[@]}" ps beat | grep -q "Up"
}

# Captured independently — NOT assumed to all match STORMPULSE_IMAGE.
# `worker` has its own image variable (STORMPULSE_WORKER_IMAGE, the
# `-satellite` variant when SATELLITE_ENABLED=true — see
# docker-compose.prod.yml); `beat` currently shares api's image but is
# captured on its own too in case that ever changes. This is exactly the
# gap ADR-0056 fixes: the previous version of this script only ever
# recorded/restored api and web, so a rollback left worker (and,
# incidentally, beat) on the new — possibly broken — image.
PREV_API_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-api-1 2>/dev/null || echo "")"
PREV_WEB_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-web-1 2>/dev/null || echo "")"
PREV_WORKER_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-worker-1 2>/dev/null || echo "")"
PREV_BEAT_IMAGE="$(docker inspect --format='{{.Config.Image}}' stormpulse-beat-1 2>/dev/null || echo "")"
echo "Previous images (kept for rollback): api=${PREV_API_IMAGE:-<none, first deploy>} web=${PREV_WEB_IMAGE:-<none>} worker=${PREV_WORKER_IMAGE:-<none>} beat=${PREV_BEAT_IMAGE:-<none>}"

# Every deploy publishes brand-new, immutable per-commit tags
# (sha-XXXXXXX) — nothing ever removes an *old* tagged image, only the
# `docker image prune -f` at the very end of this script, which only ever
# touches dangling (untagged) layers. Left unchecked, disk fills with
# every superseded StormPulse image tag from every past deploy, and the
# failure mode is exactly what this fixes: `docker compose pull` (and,
# worse, the rollback it triggers) failing with "no space left on
# device" — confirmed live in production (items 3/4/5 of the Radar
# Competitivo sequence all failed to deploy this way on 2026-08-26,
# see ADR-0067). Runs proactively, every deploy, *before* pulling new
# images — not just as post-success cleanup — so a server that's already
# jammed from a prior failed deploy still self-heals on the next attempt.
# Scoped to this project's own image repository only (never `docker
# system prune -a`, which could remove images belonging to something
# else entirely on a shared host) and never removes an image this
# deploy's own rollback might still need.
echo "==> Pruning superseded StormPulse image tags (keeps only what's currently running)"
{
  docker images --filter "reference=ghcr.io/felipeaugusantos/stormpulse*" --format "{{.Repository}}:{{.Tag}}" |
    while IFS= read -r img; do
      case "$img" in
      "$PREV_API_IMAGE" | "$PREV_WEB_IMAGE" | "$PREV_WORKER_IMAGE" | "$PREV_BEAT_IMAGE") continue ;;
      esac
      docker rmi "$img" >/dev/null 2>&1 || true
    done
} || echo "WARNING: image pruning step failed — continuing deploy anyway (not fatal)."

rollback() {
  trap - ERR # never recurse if rollback itself fails
  echo "!!! Deploy failed — dumping the last 200 log lines per service:"
  "${COMPOSE[@]}" logs --no-color --tail 200 || true

  if [ -z "$PREV_API_IMAGE" ]; then
    echo "##############################################################"
    echo "# No previous image recorded (first deploy on this server?). #"
    echo "# Nothing to roll back to — MANUAL INTERVENTION REQUIRED.    #"
    echo "##############################################################"
    exit 1
  fi

  echo "==> Validating every previous image is still available locally before rolling back"
  local missing=0
  for img in "$PREV_API_IMAGE" "$PREV_WEB_IMAGE" "$PREV_WORKER_IMAGE" "$PREV_BEAT_IMAGE"; do
    if [ -n "$img" ] && ! docker image inspect "$img" >/dev/null 2>&1; then
      echo "ERROR: previous image '$img' is no longer available locally."
      missing=1
    fi
  done
  if [ "$missing" -eq 1 ]; then
    echo "##############################################################"
    echo "# ROLLBACK ABORTED — one or more previous images are missing.#"
    echo "# The stack is in an unknown/mixed state.                    #"
    echo "# MANUAL INTERVENTION REQUIRED — see infra/README.md § Rollback. #"
    echo "##############################################################"
    exit 1
  fi

  # worker/beat fall back to PREV_API_IMAGE when no independent previous
  # value was recorded (e.g. first-ever deploy where they happened to
  # share api's image already) — never left unset, which would silently
  # inherit whatever STORMPULSE_WORKER_IMAGE/nothing this *failed* deploy
  # itself exported into the environment.
  local rollback_worker_image="${PREV_WORKER_IMAGE:-$PREV_API_IMAGE}"
  local rollback_beat_image="${PREV_BEAT_IMAGE:-$PREV_API_IMAGE}"
  echo "==> Rolling back to the previous images: api=$PREV_API_IMAGE web=$PREV_WEB_IMAGE worker=$rollback_worker_image beat=$rollback_beat_image"

  if STORMPULSE_IMAGE="$PREV_API_IMAGE" \
    STORMPULSE_WEB_IMAGE="$PREV_WEB_IMAGE" \
    STORMPULSE_WORKER_IMAGE="$rollback_worker_image" \
    "${COMPOSE[@]}" up -d api worker beat web; then
    echo "==> Rollback images applied — verifying the rolled-back stack is actually healthy"
    if wait_for_ready && verify_stack_healthy; then
      echo "==> Rollback confirmed healthy — production is back on the previous, known-good images."
      echo "==> Reminder: migrations are never auto-downgraded. If this deploy's migration already"
      echo "    ran and is incompatible with the rolled-back code, see infra/README.md § Rollback"
      echo "    for the manual 'alembic downgrade' procedure."
      exit 1
    fi
  fi

  echo "##################################################################"
  echo "# ROLLBACK FAILED (or the rolled-back stack isn't healthy either).#"
  echo "# MANUAL INTERVENTION REQUIRED — production may be degraded/down. #"
  echo "#  1. SSH in and check:  docker compose -f docker-compose.yml \\   #"
  echo "#     -f docker-compose.prod.yml ps                               #"
  echo "#  2. Check logs:        ...same command... logs --tail 200       #"
  echo "#  3. See infra/README.md § Rollback for manual recovery steps.   #"
  echo "##################################################################"
  exit 1
}
trap rollback ERR

echo "==> Pulling images for this deploy"
"${COMPOSE[@]}" pull

echo "==> Ensuring Postgres/Redis are up and healthy"
"${COMPOSE[@]}" up -d db redis
# shellcheck disable=SC2016 # intentional: single-quoted so $(...) expands
# inside the `bash -c` subshell (each loop iteration), not once here.
timeout 60 bash -c '
  until [ "$(docker inspect --format="{{.State.Health.Status}}" stormpulse-db-1 2>/dev/null)" = healthy ] &&
        [ "$(docker inspect --format="{{.State.Health.Status}}" stormpulse-redis-1 2>/dev/null)" = healthy ]; do
    sleep 2
  done
'
echo "Postgres and Redis are healthy."

# Mandatory by default (ADR-0056) — a deploy that runs migrations without
# a fresh backup has no way back if the migration itself corrupts data
# (an `alembic downgrade` reverses *schema*, not data lost to a buggy
# migration). ALLOW_DEPLOY_WITHOUT_BACKUP=true is an explicit, auditable
# escape hatch for exactly one situation: backup infrastructure itself is
# broken and an urgent fix can't wait — never a silent default.
ALLOW_DEPLOY_WITHOUT_BACKUP="${ALLOW_DEPLOY_WITHOUT_BACKUP:-false}"
echo "==> Pre-deploy backup (mandatory — set ALLOW_DEPLOY_WITHOUT_BACKUP=true to override; see infra/README.md § Backup)"
if POSTGRES_USER="${POSTGRES_USER:-stormpulse}" POSTGRES_DB="${POSTGRES_DB:-stormpulse}" \
  ./infra/backup-postgres.sh; then
  echo "Pre-deploy backup succeeded."
elif [ "$ALLOW_DEPLOY_WITHOUT_BACKUP" = "true" ]; then
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  echo "!!! WARNING: PRE-DEPLOY BACKUP FAILED — PROCEEDING WITHOUT ONE      !!!"
  echo "!!! ALLOW_DEPLOY_WITHOUT_BACKUP=true was set explicitly.           !!!"
  echo "!!! If the migration below breaks the database, there is NO fresh  !!!"
  echo "!!! backup to restore from for this specific deploy.               !!!"
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  # COMMIT_SHA (not GITHUB_SHA) is what .github/workflows/ci.yml's `deploy`
  # job actually exports into this script's environment over SSH.
  audit_line="AUDIT $(date -u +%Y-%m-%dT%H:%M:%SZ): deploy proceeded WITHOUT a pre-deploy backup (ALLOW_DEPLOY_WITHOUT_BACKUP=true), commit=${COMMIT_SHA:-unknown}"
  echo "$audit_line" | tee -a /var/log/stormpulse-deploy-audit.log 2>/dev/null || echo "$audit_line"
else
  echo "!!! Pre-deploy backup failed and ALLOW_DEPLOY_WITHOUT_BACKUP is not 'true' — aborting"
  echo "!!! before touching migrations. Fix the backup (disk space? Postgres reachable?), or"
  echo "!!! explicitly set ALLOW_DEPLOY_WITHOUT_BACKUP=true to proceed at your own risk."
  exit 1
fi

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
    sed "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" infra/tls/nginx-https.conf >infra/tls/nginx.conf.active
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
wait_for_ready

echo "==> Functional smoke test"
verify_stack_healthy

echo "==> Persisting this deploy's image tags to .env"
# Without this, .env never carries STORMPULSE_IMAGE/STORMPULSE_WEB_IMAGE/
# STORMPULSE_WORKER_IMAGE at all, so any *manual* `docker compose up -d`
# run later without explicitly exporting them first — e.g. someone on the
# server just re-applying a config change — silently falls back to
# docker-compose.prod.yml's hardcoded `:latest`, an image nothing on this
# branch's pipeline has ever actually published. That's a stale-rollback
# footgun, not a hypothetical one — it happened for real (see ADR-0050).
# Placed after every health/smoke-test check above and after `trap - ERR`,
# so a failed deploy (rolled back to the previous images) never persists
# the failed tag as if it had succeeded.
_persist_env_var() {
  local key="$1" value="$2"
  [ -z "$value" ] && return
  if grep -q "^${key}=" .env 2>/dev/null; then
    sed -i "s#^${key}=.*#${key}=${value}#" .env
  else
    echo "${key}=${value}" >>.env
  fi
}
trap - ERR
_persist_env_var STORMPULSE_IMAGE "${STORMPULSE_IMAGE:-}"
_persist_env_var STORMPULSE_WEB_IMAGE "${STORMPULSE_WEB_IMAGE:-}"
_persist_env_var STORMPULSE_WORKER_IMAGE "${STORMPULSE_WORKER_IMAGE:-}"

echo "==> Deploy confirmed."
docker image prune -f || true
