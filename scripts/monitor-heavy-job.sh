#!/usr/bin/env bash
#
# Poll resource-trend data (thermal, load, memory, disk free) while a named systemd
# unit is active, logging to a durable file. See ADR 0014.
#
# Why: persistent journald (once enabled by harden.yml) captures a unit's own
# stdout/stderr and start/stop/exit-status, but not the host's resource *trend* over
# a multi-hour run. This closes that gap -- if a future incident happens again, there's
# a real trail to correlate against (was memory climbing? did temp spike right before?)
# instead of no data at all, which is what happened this time.
#
# Usage:  ./scripts/monitor-heavy-job.sh <systemd-unit-name> [interval-seconds]
set -euo pipefail

UNIT="${1:?Usage: monitor-heavy-job.sh <systemd-unit-name> [interval-seconds]}"
INTERVAL="${2:-300}" # 5 minutes by default

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${REPO_ROOT}/local/monitoring"
LOG_PATH="${LOG_DIR}/${UNIT}.log"
mkdir -p "${LOG_DIR}"

echo "==> Monitoring unit '${UNIT}' every ${INTERVAL}s -> ${LOG_PATH}"
echo "    Exits automatically once the unit is no longer active."

sample() {
  local ts temp_raw temp_c load mem_avail disk_free
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  temp_raw="$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo '')"
  if [[ -n "${temp_raw}" ]]; then
    temp_c="$(awk -v t="${temp_raw}" 'BEGIN { printf "%.1f", t / 1000 }')"
  else
    temp_c="n/a"
  fi
  load="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo 'n/a')"
  mem_avail="$(awk '/MemAvailable/ {printf "%.0f", $2/1024}' /proc/meminfo 2>/dev/null || echo 'n/a')"
  disk_free="$(df -Ph /mnt/data 2>/dev/null | awk 'NR==2 {print $4}' || echo 'n/a')"
  echo "${ts} temp_c=${temp_c} load=${load} mem_available_mb=${mem_avail} disk_free=${disk_free}"
}

sample | tee -a "${LOG_PATH}"

while systemctl is-active --quiet "${UNIT}" 2>/dev/null; do
  sleep "${INTERVAL}"
  sample | tee -a "${LOG_PATH}"
done

echo "==> Unit '${UNIT}' is no longer active. Final status:"
systemctl status "${UNIT}" --no-pager 2>&1 | tee -a "${LOG_PATH}" || true
echo "==> Full trend log: ${LOG_PATH}"
