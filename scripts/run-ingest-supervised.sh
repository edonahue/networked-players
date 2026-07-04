#!/usr/bin/env bash
#
# Run scripts/run-ingest.sh as a supervised systemd transient unit instead of a bare
# background shell process, and automatically launch a second transient unit running
# scripts/monitor-heavy-job.sh alongside it. See ADR 0014.
#
# Why: a bare `&`-backgrounded process is tied to the shell/tool session that started
# it and gives no resource accounting or durable logging on its own. A systemd
# transient unit survives SSH/session disconnects robustly, gets real cgroup resource
# limits (Nice, I/O scheduling class, a memory ceiling), and -- once
# infra/ansible/playbooks/harden.yml's persistent journald change is applied --
# durable logging via `journalctl -u <unit>` independent of any scratch file.
# Auto-launching the monitor means one command gets you periodic ntfy check-ins and a
# final completion notification with zero ongoing Claude Code tokens and no second
# manual step -- you can close everything and still get notified.
#
# Requires sudo (a system-level transient unit is more robust than a --user unit,
# which needs `loginctl enable-linger` to survive logout). The workload itself runs
# as your normal user, not root -- only the unit *creation* needs root.
#
# Configure via the same environment variables as run-ingest.sh (SNAPSHOT required;
# MAX_RELEASES, OVERWRITE, RAW_DIR, PROCESSED_DIR, MANIFEST_DIR optional), or an optional
# git-ignored local/ingest.env. NTFY_URL (see ~/.bashrc) is passed through if set;
# notifications are silently skipped otherwise (scripts/lib/notify.sh degrades
# gracefully).
#
# EXPECTED_TOTAL_RELEASES (optional): gives monitor-heavy-job.sh's ntfy check-ins a
# real percentage and ETA for a full/unbounded run, where MAX_RELEASES (which already
# doubles as the expected total for a bounded slice) isn't set. Most useful for a
# REPEAT run of a snapshot that's already been fully parsed once -- its real total is
# already known (e.g. EXPECTED_TOTAL_RELEASES=19192301 for a rerun of 20260601, whose
# real count was recorded in docs/DISCOGS_INGESTION.md). For a brand-new snapshot with
# no prior run, there's no reliable known total -- omit it and check-ins still report a
# rate (releases/hour), just without a %/ETA, rather than guessing at a number nothing
# backs.
#
# Usage:  SNAPSHOT=20260601 ./scripts/run-ingest-supervised.sh
#         SNAPSHOT=20260601 MAX_RELEASES=50000 ./scripts/run-ingest-supervised.sh
#         SNAPSHOT=20260601 EXPECTED_TOTAL_RELEASES=19192301 ./scripts/run-ingest-supervised.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/notify.sh"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi
: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD (first of month), e.g. SNAPSHOT=20260601}"

TIMESTAMP="$(date +%s)"
UNIT_NAME="discogs-ingest-${SNAPSHOT}-${TIMESTAMP}"
MONITOR_UNIT_NAME="discogs-monitor-${SNAPSHOT}-${TIMESTAMP}"

echo "==> Starting supervised unit: ${UNIT_NAME}"
echo "    Nice=10, best-effort I/O scheduling, MemoryMax=4G (observed real usage is"
echo "    ~168MB -- this is a generous safety ceiling, not a tight constraint)."

# --collect: garbage-collect the unit automatically once it exits, rather than
# leaving a stopped-but-not-cleaned-up transient unit behind on every run.
sudo systemd-run \
  --unit="${UNIT_NAME}" \
  --description="Discogs ingest ${SNAPSHOT}${MAX_RELEASES:+ (max ${MAX_RELEASES})}" \
  --collect \
  --property="Nice=10" \
  --property="IOSchedulingClass=best-effort" \
  --property="IOSchedulingPriority=7" \
  --property="MemoryMax=4G" \
  --working-directory="${REPO_ROOT}" \
  --uid="$(id -u)" \
  --gid="$(id -g)" \
  env \
    "HOME=${HOME}" \
    "PATH=${HOME}/.local/bin:${PATH}" \
    "SNAPSHOT=${SNAPSHOT}" \
    "MAX_RELEASES=${MAX_RELEASES:-}" \
    "OVERWRITE=${OVERWRITE:-}" \
    "RAW_DIR=${RAW_DIR:-}" \
    "PROCESSED_DIR=${PROCESSED_DIR:-}" \
    "MANIFEST_DIR=${MANIFEST_DIR:-}" \
    "${REPO_ROOT}/scripts/run-ingest.sh"

echo "==> Started as systemd unit: ${UNIT_NAME}"
echo "    Follow live:  journalctl -u ${UNIT_NAME} -f"
echo "    Status:       systemctl status ${UNIT_NAME}"
echo "    Stop early:   sudo systemctl stop ${UNIT_NAME}"
echo "    Resource use: systemctl status ${UNIT_NAME} (shows Memory/CPU/Tasks)"

notify "Started: ${UNIT_NAME}" \
  "Snapshot ${SNAPSHOT}${MAX_RELEASES:+, max ${MAX_RELEASES} releases}. Check-ins every 30 min." \
  "low" "rocket"

# MAX_RELEASES already IS the expected total for a bounded slice; for a full run,
# fall back to the operator-supplied EXPECTED_TOTAL_RELEASES (a known prior total),
# or leave blank (rate-only check-ins, no %/ETA) rather than guess.
MONITOR_EXPECTED_TOTAL="${MAX_RELEASES:-${EXPECTED_TOTAL_RELEASES:-}}"

echo "==> Starting monitor unit: ${MONITOR_UNIT_NAME} (ntfy check-ins every 30 min)"
sudo systemd-run \
  --unit="${MONITOR_UNIT_NAME}" \
  --description="Monitor for ${UNIT_NAME}" \
  --collect \
  --working-directory="${REPO_ROOT}" \
  --uid="$(id -u)" \
  --gid="$(id -g)" \
  env \
    "HOME=${HOME}" \
    "PATH=${HOME}/.local/bin:${PATH}" \
    "NTFY_URL=${NTFY_URL:-}" \
    "${REPO_ROOT}/scripts/monitor-heavy-job.sh" "${UNIT_NAME}" 1800 "${MONITOR_EXPECTED_TOTAL}"

echo "==> Started as systemd unit: ${MONITOR_UNIT_NAME}"
echo "    Follow live:  journalctl -u ${MONITOR_UNIT_NAME} -f"
echo "    Trend log:    local/monitoring/${UNIT_NAME}.log"
echo "==> Both units run independently of this shell/session. You'll get an ntfy"
echo "    check-in roughly every 30 min, and a final notification when it's done."
