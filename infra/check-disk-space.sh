#!/usr/bin/env bash
# StormPulse — disk-space alert for the platform operator.
#
# The disk-full incident of 2026-08-26 (ADR-0067 — Docker images piling up
# blocked 3 deploys in a row) was only caught by manually reading CI logs;
# nothing paged anyone, and the app itself kept running the whole time, so
# nothing in the running stack would have noticed either. This runs
# independently of whether any StormPulse container is even up — a host
# with a full disk can't be trusted to run its own alerting from inside a
# container that might itself be unable to start.
#
# Meant to run on a schedule (crontab entry in infra/README.md), never as
# part of deploy.sh — deploy.sh's own proactive image pruning (ADR-0067)
# is the fix for the specific cause found there; this is the general
# safety net for whatever fills the disk next (logs, backups, a runaway
# volume — anything).
#
# State file tracks whether an alert is already "open" so a disk stuck
# above the threshold for a week sends exactly one email, not one per cron
# tick — and sends a single "back to normal" email on recovery, so silence
# during the alert window doesn't read as "still broken, nobody's looking."

set -euo pipefail

DISK_CHECK_PATH="${DISK_CHECK_PATH:-/}"
DISK_ALERT_THRESHOLD_PERCENT="${DISK_ALERT_THRESHOLD_PERCENT:-80}"
# Falls back to PLATFORM_ADMIN_EMAIL (same person, already configured for
# the platform-admin bootstrap) — set DISK_ALERT_EMAIL explicitly only if
# ops alerts should go somewhere else.
DISK_ALERT_EMAIL="${DISK_ALERT_EMAIL:-${PLATFORM_ADMIN_EMAIL:-}}"
SES_FROM_EMAIL="${SES_FROM_EMAIL:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_FILE="${DISK_ALERT_STATE_FILE:-/var/lib/stormpulse/disk-alert.state}"

usage_percent="$(df -P "$DISK_CHECK_PATH" | awk 'NR==2 { gsub("%", "", $5); print $5 }')"
if [ -z "$usage_percent" ]; then
  echo "ERROR: could not read disk usage for $DISK_CHECK_PATH" >&2
  exit 1
fi
echo "Disk usage at $DISK_CHECK_PATH: ${usage_percent}% (threshold ${DISK_ALERT_THRESHOLD_PERCENT}%)"

# Credentials always come from the environment/instance IAM role, never a
# CLI flag (same rule as backup-postgres.sh's S3 upload) — never echoed.
send_email() {
  local subject="$1" body="$2"
  if [ -z "$DISK_ALERT_EMAIL" ] || [ -z "$SES_FROM_EMAIL" ]; then
    echo "WARNING: DISK_ALERT_EMAIL/SES_FROM_EMAIL not configured — logging only, no email sent." >&2
    return 0
  fi
  if ! command -v aws >/dev/null 2>&1; then
    echo "WARNING: 'aws' CLI not installed — logging only, no email sent." >&2
    return 0
  fi
  # A JSON file, not the CLI's inline shorthand syntax — the shorthand
  # parser breaks on the commas/braces this script's own messages contain.
  local json_file
  json_file="$(mktemp)"
  trap 'rm -f "$json_file"' RETURN
  cat >"$json_file" <<EOF
{
  "Source": "$SES_FROM_EMAIL",
  "Destination": {"ToAddresses": ["$DISK_ALERT_EMAIL"]},
  "Message": {
    "Subject": {"Data": "$subject"},
    "Body": {"Text": {"Data": "$body"}}
  }
}
EOF
  aws ses send-email --region "$AWS_REGION" --cli-input-json "file://$json_file" >/dev/null ||
    echo "WARNING: SES send-email failed — see logs." >&2
}

mkdir -p "$(dirname "$STATE_FILE")"
already_alerted="false"
[ -f "$STATE_FILE" ] && already_alerted="true"

if [ "$usage_percent" -ge "$DISK_ALERT_THRESHOLD_PERCENT" ]; then
  if [ "$already_alerted" = "false" ]; then
    echo "==> Threshold crossed — sending alert to ${DISK_ALERT_EMAIL:-<not configured>}"
    send_email \
      "[StormPulse] Disco em ${usage_percent}% no servidor de producao" \
      "O disco em ${DISK_CHECK_PATH} esta em ${usage_percent}% de uso (limite configurado: ${DISK_ALERT_THRESHOLD_PERCENT}%). Veja infra/README.md secao Disco cheio para os comandos de diagnostico e limpeza."
    date -u +%Y-%m-%dT%H:%M:%SZ >"$STATE_FILE"
  else
    echo "Already alerted (since $(cat "$STATE_FILE")) — not re-sending."
  fi
elif [ "$already_alerted" = "true" ]; then
  echo "==> Usage back under threshold — sending recovery notice"
  send_email \
    "[StormPulse] Disco normalizado (${usage_percent}%)" \
    "O disco em ${DISK_CHECK_PATH} voltou a ${usage_percent}% de uso, abaixo do limite de ${DISK_ALERT_THRESHOLD_PERCENT}%."
  rm -f "$STATE_FILE"
fi
