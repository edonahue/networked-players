#!/usr/bin/env bash
#
# Poll resource-trend data (thermal, load, memory, disk free) and a rough progress
# estimate while a named systemd unit is active, logging to a durable file and
# sending periodic ntfy check-ins. See ADR 0014.
#
# Why: persistent journald (once enabled by harden.yml) captures a unit's own
# stdout/stderr and start/stop/exit-status, but not the host's resource *trend* over
# a multi-hour run, and doesn't push anything to you proactively. This closes both
# gaps -- a real trail to correlate a future incident against, and scheduled check-ins
# instead of anyone (human or Claude Code session) actively watching the job.
#
# Usage:  ./scripts/monitor-heavy-job.sh <systemd-unit-name> [interval-seconds] [expected-total-releases]
#
# interval-seconds defaults to 1800 (30 min) -- check-ins are the primary purpose now,
# not just a resource-trend log. expected-total-releases is optional: pass it (e.g.
# the same MAX_RELEASES a bounded run used) for a real percentage; omitted, progress
# is still reported as raw counts, just without a %.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/notify.sh"

UNIT="${1:?Usage: monitor-heavy-job.sh <systemd-unit-name> [interval-seconds] [expected-total-releases]}"
INTERVAL="${2:-1800}"
EXPECTED_TOTAL="${3:-}"
# Chunk size assumed for the progress estimate -- matches parse-releases' own
# --chunk-releases default (parquet.py). Not read back from the real invocation;
# this is a best-effort estimate, not an exact count.
ASSUMED_CHUNK_RELEASES=5000

LOG_DIR="${REPO_ROOT}/local/monitoring"
LOG_PATH="${LOG_DIR}/${UNIT}.log"
mkdir -p "${LOG_DIR}"

# discogs-ingest-<snapshot>-<epoch> (run-ingest-supervised.sh's naming) -- best-effort
# parse; progress estimation is skipped gracefully if this doesn't match.
SNAPSHOT=""
if [[ "${UNIT}" =~ ^discogs-ingest-([0-9]{8})-[0-9]+$ ]]; then
  SNAPSHOT="${BASH_REMATCH[1]}"
fi

echo "==> Monitoring unit '${UNIT}' every ${INTERVAL}s -> ${LOG_PATH}"
echo "    Exits automatically once the unit is no longer active."

progress_line() {
  if [[ -z "${SNAPSHOT}" ]]; then
    echo "progress=n/a (unit name doesn't match the expected discogs-ingest-<snapshot>-<epoch> pattern)"
    return
  fi
  local staging_dir parts done_estimate
  staging_dir="$(find "${REPO_ROOT}/local/processed/discogs" \
    -maxdepth 1 -type d -name ".snapshot=${SNAPSHOT}.tmp-*" 2>/dev/null | head -1)"
  if [[ -z "${staging_dir}" ]]; then
    echo "progress=n/a (no staging directory yet)"
    return
  fi
  parts="$(find "${staging_dir}/table=releases" -maxdepth 1 -name '*.parquet' 2>/dev/null | wc -l | tr -d ' ')"
  done_estimate=$(( parts * ASSUMED_CHUNK_RELEASES ))
  if [[ -n "${EXPECTED_TOTAL}" && "${EXPECTED_TOTAL}" -gt 0 ]]; then
    local pct
    pct="$(awk -v d="${done_estimate}" -v t="${EXPECTED_TOTAL}" 'BEGIN { printf "%.1f", (d/t)*100 }')"
    echo "progress=~${done_estimate}/${EXPECTED_TOTAL} releases (~${pct}%, ${parts} parts written)"
  else
    echo "progress=~${done_estimate} releases so far (${parts} parts written, no expected total given)"
  fi
}

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
  echo "${ts} temp_c=${temp_c} load=${load} mem_available_mb=${mem_avail} disk_free=${disk_free} $(progress_line)"
}

first_sample="$(sample)"
echo "${first_sample}" | tee -a "${LOG_PATH}"
notify "Monitoring started: ${UNIT}" "${first_sample}" "low" "hourglass_flowing_sand"

while systemctl is-active --quiet "${UNIT}" 2>/dev/null; do
  sleep "${INTERVAL}"
  this_sample="$(sample)"
  echo "${this_sample}" | tee -a "${LOG_PATH}"
  notify "Check-in: ${UNIT}" "${this_sample}" "low" "hourglass_flowing_sand"
done

echo "==> Unit '${UNIT}' is no longer active. Final status:"
final_status="$(systemctl status "${UNIT}" --no-pager 2>&1 || true)"
echo "${final_status}" | tee -a "${LOG_PATH}"
echo "==> Full trend log: ${LOG_PATH}"

if echo "${final_status}" | grep -q "Active: active\|Active: activating"; then
  # Shouldn't happen (the loop above only exits once is-active reports false), but
  # guard against a race rather than send a misleading notification either way.
  notify "Finished (status unclear): ${UNIT}" "Check journalctl -u ${UNIT} directly." "default" "warning"
elif echo "${final_status}" | grep -qE "Active: failed|code=exited, status=[1-9]"; then
  notify "FAILED: ${UNIT}" "$(progress_line)
See: journalctl -u ${UNIT} --no-pager" "urgent" "x"
else
  notify "Finished: ${UNIT}" "$(progress_line)" "high" "white_check_mark"
fi
