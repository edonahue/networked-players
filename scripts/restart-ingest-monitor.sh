#!/usr/bin/env bash
#
# Restart the ntfy monitor for an already-running run-ingest-supervised.sh unit, this
# time with a known EXPECTED_TOTAL_RELEASES so check-ins get a real percentage and
# ETA. Useful when a run started without a known total (a brand-new snapshot) and the
# total becomes known partway through, or when restarting to pick up a fixed
# monitor-heavy-job.sh mid-run. Only the monitor is stopped/restarted -- the actual
# ingest process (manifest/download/parse-releases/validate) is never touched.
#
# Usage: ./scripts/restart-ingest-monitor.sh <ingest-unit-name> <expected-total-releases> [interval-seconds]
#   ./scripts/restart-ingest-monitor.sh discogs-ingest-20260601-1783095742 19192301
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

INGEST_UNIT="${1:?Usage: $0 <ingest-unit-name> <expected-total-releases> [interval-seconds]}"
EXPECTED_TOTAL="${2:?Usage: $0 <ingest-unit-name> <expected-total-releases> [interval-seconds]}"
INTERVAL="${3:-1800}"

if ! systemctl is-active --quiet "${INGEST_UNIT}.service" 2>/dev/null; then
  echo "ABORT: ${INGEST_UNIT}.service is not active -- nothing to monitor." >&2
  exit 1
fi

# Discover the currently-running monitor by its Description (every monitor
# this script or run-ingest-supervised.sh creates names it "Monitor for
# <ingest-unit> ..."), rather than assuming a fixed name-derivation pattern.
# Real gap this fixes: the original version assumed
# discogs-ingest-X -> discogs-monitor-X (run-ingest-supervised.sh's own
# naming), which breaks the second time this script runs -- a monitor
# restarted BY this script is named discogs-monitor-restart-<epoch>, not
# discogs-monitor-<snapshot>-<epoch>, so the fixed-pattern guess silently
# missed it ("already stopped or never existed") while the real monitor
# kept running untouched. Confirmed live.
mapfile -t OLD_MONITOR_UNITS < <(
  systemctl list-units 'discogs-monitor-*.service' --all --no-legend --plain 2>/dev/null \
    | awk '{print $1}' \
    | while read -r unit; do
        systemctl show "${unit}" --property=Description --value 2>/dev/null \
          | grep -qE "^Monitor for ${INGEST_UNIT}($| )" && echo "${unit}"
      done
)
NEW_MONITOR_UNIT="discogs-monitor-restart-$(date +%s)"

if [[ "${#OLD_MONITOR_UNITS[@]}" -eq 0 ]]; then
  echo "==> No running monitor found for ${INGEST_UNIT} -- nothing to stop, starting fresh."
else
  for old_unit in "${OLD_MONITOR_UNITS[@]}"; do
    echo "==> Stopping old monitor: ${old_unit}"
    sudo systemctl stop "${old_unit}"
  done
fi

echo "==> Starting new monitor with EXPECTED_TOTAL_RELEASES=${EXPECTED_TOTAL}: ${NEW_MONITOR_UNIT}"
sudo systemd-run \
  --unit="${NEW_MONITOR_UNIT}" \
  --description="Monitor for ${INGEST_UNIT} (restarted with a known total)" \
  --collect \
  --working-directory="${REPO_ROOT}" \
  --uid="$(id -u)" \
  --gid="$(id -g)" \
  env \
    "HOME=${HOME}" \
    "PATH=${HOME}/.local/bin:${PATH}" \
    "NTFY_URL=${NTFY_URL:-}" \
    "${REPO_ROOT}/scripts/monitor-heavy-job.sh" "${INGEST_UNIT}" "${INTERVAL}" "${EXPECTED_TOTAL}"

echo "==> Done. Follow live:  journalctl -u ${NEW_MONITOR_UNIT} -f"
echo "    Expect a 'Monitoring started' ntfy notification within a few seconds."
