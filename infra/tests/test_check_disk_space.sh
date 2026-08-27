#!/usr/bin/env bash
# Tests for infra/check-disk-space.sh — stub `df`/`aws` on PATH, so this
# never touches the real filesystem usage or sends a real email. Run:
# ./infra/tests/test_check_disk_space.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

FAILED=0
pass() { echo "PASS: $1"; }
fail() {
  echo "FAIL: $1"
  FAILED=1
}

# Guards against exactly the bug that slipped past this suite once
# already: the script committed without its executable bit set (git mode
# 100644 instead of 100755) made every scenario that expects a file to be
# CREATED fail with "Permission denied" — but scenarios expecting NO file
# to be created (below-threshold, already-alerted) passed anyway, since
# "the script never ran at all" also satisfies "no file was created".
# Checked explicitly here so that specific failure mode is loud, not a
# silent false-positive on half the scenarios.
if [ ! -x "./infra/check-disk-space.sh" ]; then
  fail "infra/check-disk-space.sh is not executable (git mode must be 100755 — run: git update-index --chmod=+x infra/check-disk-space.sh)"
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"

# `df -P <path>` — capacity column driven by STUB_DISK_PERCENT.
cat >"$WORK/bin/df" <<'STUB'
#!/usr/bin/env bash
echo "Filesystem     1024-blocks      Used Available Capacity Mounted on"
echo "/dev/root       10000000   5000000   5000000      ${STUB_DISK_PERCENT:-50}% /"
STUB
chmod +x "$WORK/bin/df"

# Logs every call so tests can assert whether an email was (or wasn't)
# attempted, without ever touching real SES.
cat >"$WORK/bin/aws" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"${STUB_STATE_DIR:?}/aws.log"
[ "${STUB_AWS_FAIL:-false}" = "true" ] && exit 1
exit 0
STUB
chmod +x "$WORK/bin/aws"

export PATH="$WORK/bin:$PATH"

run() {
  local state_dir="$1"
  shift
  STUB_STATE_DIR="$state_dir" "$@" ./infra/check-disk-space.sh >"$state_dir/out.log" 2>&1
}

# --- Scenario 1: usage below threshold, no prior alert — silent, no email ---
S1="$WORK/s1"
mkdir -p "$S1"
run "$S1" env STUB_DISK_PERCENT=50 DISK_ALERT_THRESHOLD_PERCENT=80 \
  DISK_ALERT_EMAIL=admin@example.com SES_FROM_EMAIL=noreply@example.com \
  DISK_ALERT_STATE_FILE="$S1/state"
if [ ! -f "$S1/aws.log" ] && [ ! -f "$S1/state" ]; then
  pass "below threshold: no email sent, no state file created"
else
  fail "below threshold: unexpectedly sent an email or created a state file"
fi

# --- Scenario 2: usage above threshold, first time — sends exactly one alert ---
S2="$WORK/s2"
mkdir -p "$S2"
run "$S2" env STUB_DISK_PERCENT=95 DISK_ALERT_THRESHOLD_PERCENT=80 \
  DISK_ALERT_EMAIL=admin@example.com SES_FROM_EMAIL=noreply@example.com \
  DISK_ALERT_STATE_FILE="$S2/state"
if [ -f "$S2/aws.log" ] && grep -q "send-email" "$S2/aws.log" && [ -f "$S2/state" ]; then
  pass "above threshold (first time): sends an alert and opens a state file"
else
  fail "above threshold (first time): did not alert or did not open a state file"
fi

# --- Scenario 3: still above threshold, alert already open — no duplicate ---
S3="$WORK/s3"
mkdir -p "$S3"
echo "2026-01-01T00:00:00Z" >"$S3/state"
run "$S3" env STUB_DISK_PERCENT=95 DISK_ALERT_THRESHOLD_PERCENT=80 \
  DISK_ALERT_EMAIL=admin@example.com SES_FROM_EMAIL=noreply@example.com \
  DISK_ALERT_STATE_FILE="$S3/state"
if [ ! -f "$S3/aws.log" ]; then
  pass "above threshold (already alerted): does not re-send"
else
  fail "above threshold (already alerted): sent a duplicate email"
fi

# --- Scenario 4: usage recovered, alert was open — sends recovery, clears state ---
S4="$WORK/s4"
mkdir -p "$S4"
echo "2026-01-01T00:00:00Z" >"$S4/state"
run "$S4" env STUB_DISK_PERCENT=40 DISK_ALERT_THRESHOLD_PERCENT=80 \
  DISK_ALERT_EMAIL=admin@example.com SES_FROM_EMAIL=noreply@example.com \
  DISK_ALERT_STATE_FILE="$S4/state"
if [ -f "$S4/aws.log" ] && grep -q "send-email" "$S4/aws.log" && [ ! -f "$S4/state" ]; then
  pass "recovered below threshold: sends a recovery notice and clears the state file"
else
  fail "recovered below threshold: did not send recovery notice or state file still present"
fi

# --- Scenario 5: no email/sender configured — never crashes, no email attempted ---
S5="$WORK/s5"
mkdir -p "$S5"
run "$S5" env STUB_DISK_PERCENT=95 DISK_ALERT_THRESHOLD_PERCENT=80 \
  DISK_ALERT_STATE_FILE="$S5/state"
rc=$?
if [ "$rc" -eq 0 ] && [ ! -f "$S5/aws.log" ]; then
  pass "unconfigured email: exits 0, logs only, never calls aws"
else
  fail "unconfigured email: exited nonzero or attempted to call aws anyway"
fi

if [ "$FAILED" -eq 0 ]; then
  echo "All check-disk-space.sh tests passed."
else
  echo "Some check-disk-space.sh tests FAILED."
fi
exit "$FAILED"
