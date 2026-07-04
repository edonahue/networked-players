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
# the same MAX_RELEASES a bounded run used, or a known prior total for a REPEAT run of
# an already-parsed snapshot -- e.g. EXPECTED_TOTAL_RELEASES=19192301 for a rerun of
# 20260601, whose real total was recorded in docs/DISCOGS_INGESTION.md) for a real
# percentage AND an ETA; omitted, progress is still reported as a rate (releases/hour),
# just without a percentage or a projected finish time -- see run-ingest-supervised.sh's
# EXPECTED_TOTAL_RELEASES passthrough.
#
# The trend LOG stays a compact, grep/awk-friendly key=value line per sample. The ntfy
# NOTIFICATION body is a separate, deliberately human-readable multi-line rendering --
# a phone notification is read at a glance, not parsed.
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

# Rate/ETA baseline -- set on the FIRST sample that finds real progress, not
# necessarily the first sample overall (the staging dir may not exist yet at
# t=0). Using this run's own first observation as the baseline (rather than
# assuming the job started at zero) means restarting this monitor mid-run
# (e.g. to add EXPECTED_TOTAL to an already-running ingest) still produces a
# correct rate -- it's computed from progress *since this monitor started
# watching*, not since the ingest itself began.
BASELINE_DONE=""
BASELINE_EPOCH=""

# 1,234,567 -- thousands-grouped, falls back to the raw number if printf's
# locale-grouping flag isn't available for some reason.
human_count() {
  printf "%'d" "$1" 2>/dev/null || printf "%s" "$1"
}

# 7530 -> "2h 5m"; 172800 -> "2d 0h"; 90 -> "1m" (always at least one unit,
# never "0m" for a positive-but-sub-minute duration).
human_duration() {
  local total="$1" d h m
  d=$(( total / 86400 )); h=$(( (total % 86400) / 3600 )); m=$(( (total % 3600) / 60 ))
  if (( d > 0 )); then
    printf "%dd %dh" "${d}" "${h}"
  elif (( h > 0 )); then
    printf "%dh %dm" "${h}" "${m}"
  else
    printf "%dm" "$(( m > 0 ? m : 1 ))"
  fi
}

# Populates PROGRESS_* globals once per call -- shared by the compact log
# line and the human-readable notification body so the two never drift or
# recompute (and re-baseline) independently.
PROGRESS_NA_REASON=""
PROGRESS_DONE=0
PROGRESS_PARTS=0
PROGRESS_PCT=""
PROGRESS_RATE_PER_HOUR=""
PROGRESS_ETA_EPOCH=""
PROGRESS_ETA_SECONDS=""

compute_progress() {
  PROGRESS_NA_REASON=""
  PROGRESS_PCT=""
  PROGRESS_RATE_PER_HOUR=""
  PROGRESS_ETA_EPOCH=""
  PROGRESS_ETA_SECONDS=""

  if [[ -z "${SNAPSHOT}" ]]; then
    PROGRESS_NA_REASON="unit name doesn't match discogs-ingest-<snapshot>-<epoch>"
    return
  fi
  local staging_dir now
  staging_dir="$(find "${REPO_ROOT}/local/processed/discogs" \
    -maxdepth 1 -type d -name ".snapshot=${SNAPSHOT}.tmp-*" 2>/dev/null | head -1)"
  if [[ -z "${staging_dir}" ]]; then
    PROGRESS_NA_REASON="no staging directory yet"
    return
  fi
  PROGRESS_PARTS="$(find "${staging_dir}/table=releases" -maxdepth 1 -name '*.parquet' 2>/dev/null | wc -l | tr -d ' ')"
  PROGRESS_DONE=$(( PROGRESS_PARTS * ASSUMED_CHUNK_RELEASES ))
  now="$(date +%s)"

  if [[ -z "${BASELINE_EPOCH}" ]]; then
    BASELINE_DONE="${PROGRESS_DONE}"
    BASELINE_EPOCH="${now}"
  fi

  local elapsed=$(( now - BASELINE_EPOCH ))
  if (( elapsed > 0 )) && (( PROGRESS_DONE > BASELINE_DONE )); then
    PROGRESS_RATE_PER_HOUR="$(awk -v d="$(( PROGRESS_DONE - BASELINE_DONE ))" -v s="${elapsed}" \
      'BEGIN { printf "%.0f", (d/s)*3600 }')"
    if [[ -n "${EXPECTED_TOTAL}" && "${EXPECTED_TOTAL}" -gt "${PROGRESS_DONE}" ]]; then
      PROGRESS_ETA_SECONDS="$(awk -v d="${PROGRESS_DONE}" -v t="${EXPECTED_TOTAL}" \
        -v base_d="${BASELINE_DONE}" -v elapsed="${elapsed}" \
        'BEGIN { rate = (d - base_d) / elapsed; printf "%.0f", (t - d) / rate }')"
      PROGRESS_ETA_EPOCH=$(( now + PROGRESS_ETA_SECONDS ))
    fi
  fi
  if [[ -n "${EXPECTED_TOTAL}" && "${EXPECTED_TOTAL}" -gt 0 ]]; then
    PROGRESS_PCT="$(awk -v d="${PROGRESS_DONE}" -v t="${EXPECTED_TOTAL}" 'BEGIN { printf "%.1f", (d/t)*100 }')"
  fi
}

# Compact, single-line, grep/awk-friendly -- for the trend log file only.
progress_log_line() {
  if [[ -n "${PROGRESS_NA_REASON}" ]]; then
    echo "progress=n/a (${PROGRESS_NA_REASON})"
    return
  fi
  local extra=""
  [[ -n "${PROGRESS_RATE_PER_HOUR}" ]] && extra+=", ~${PROGRESS_RATE_PER_HOUR} releases/hr"
  [[ -n "${PROGRESS_ETA_EPOCH}" ]] && extra+=", eta_epoch=${PROGRESS_ETA_EPOCH}"
  if [[ -n "${PROGRESS_PCT}" ]]; then
    echo "progress=${PROGRESS_DONE}/${EXPECTED_TOTAL} releases (~${PROGRESS_PCT}%, ${PROGRESS_PARTS} parts${extra})"
  else
    echo "progress=~${PROGRESS_DONE} releases (${PROGRESS_PARTS} parts${extra}, no expected total)"
  fi
}

# Multi-line, labeled, comma-grouped numbers, a duration AND a wall-clock
# time for the ETA -- built to be read at a glance on a phone lock screen,
# not parsed.
progress_notify_lines() {
  if [[ -n "${PROGRESS_NA_REASON}" ]]; then
    echo "Progress: unavailable (${PROGRESS_NA_REASON})"
    return
  fi
  if [[ -n "${PROGRESS_PCT}" ]]; then
    echo "Progress: $(human_count "${PROGRESS_DONE}") / $(human_count "${EXPECTED_TOTAL}") releases (${PROGRESS_PCT}%, ${PROGRESS_PARTS} parts)"
  else
    echo "Progress: $(human_count "${PROGRESS_DONE}") releases so far (${PROGRESS_PARTS} parts, total unknown)"
  fi
  if [[ -n "${PROGRESS_RATE_PER_HOUR}" ]]; then
    echo "Rate: $(human_count "${PROGRESS_RATE_PER_HOUR}") releases/hour"
  fi
  if [[ -n "${PROGRESS_ETA_EPOCH}" ]]; then
    local eta_clock
    eta_clock="$(date -u -d "@${PROGRESS_ETA_EPOCH}" +"%Y-%m-%d %H:%M UTC" 2>/dev/null || echo "unknown")"
    echo "ETA: ~$(human_duration "${PROGRESS_ETA_SECONDS}") remaining (around ${eta_clock})"
  elif [[ -z "${PROGRESS_PCT}" && -n "${PROGRESS_RATE_PER_HOUR}" ]]; then
    echo "ETA: unknown -- set EXPECTED_TOTAL_RELEASES for a projected finish time"
  fi
}

# Resource-sample globals, set directly by collect_sample() (never called
# via command substitution -- see the comment on collect_sample() itself for
# why that distinction is load-bearing here, not just style).
SAMPLE_TS=""
SAMPLE_TEMP_C=""
SAMPLE_LOAD=""
SAMPLE_MEM_AVAIL=""
SAMPLE_DISK_FREE=""

# Must be called directly (collect_sample, not "$(collect_sample)") -- a
# real bug this fixes: the previous version's equivalent function was
# always invoked as "$(sample)", and command substitution forks a subshell.
# compute_progress()'s "global" PROGRESS_*/BASELINE_* writes only ever
# happened inside that throwaway subshell and vanished the instant it
# exited, so a later, separately-substituted notify_body() call always saw
# the untouched startup defaults -- confirmed live: the first real
# check-in after adding EXPECTED_TOTAL still showed "total unknown" and "0
# releases" even though EXPECTED_TOTAL was a real, correctly-passed
# argument. Renderers (progress_log_line, progress_notify_lines, and this
# function's own callers) are safe to call via "$(...)" since they only
# READ these globals -- a subshell inherits a full copy of the parent's
# variables, it just can't write back, which is exactly what a
# read-only renderer never needs to do.
collect_sample() {
  SAMPLE_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local temp_raw
  temp_raw="$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo '')"
  if [[ -n "${temp_raw}" ]]; then
    SAMPLE_TEMP_C="$(awk -v t="${temp_raw}" 'BEGIN { printf "%.1f", t / 1000 }')"
  else
    SAMPLE_TEMP_C="n/a"
  fi
  SAMPLE_LOAD="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo 'n/a')"
  SAMPLE_MEM_AVAIL="$(awk '/MemAvailable/ {printf "%.0f", $2/1024}' /proc/meminfo 2>/dev/null || echo 'n/a')"
  SAMPLE_DISK_FREE="$(df -Ph /mnt/data 2>/dev/null | awk 'NR==2 {print $4}' || echo 'n/a')"
  compute_progress
}

render_log_line() {
  echo "${SAMPLE_TS} temp_c=${SAMPLE_TEMP_C} load=${SAMPLE_LOAD} mem_available_mb=${SAMPLE_MEM_AVAIL} disk_free=${SAMPLE_DISK_FREE} $(progress_log_line)"
}

render_notify_body() {
  local temp_display="n/a"
  [[ "${SAMPLE_TEMP_C}" != "n/a" ]] && temp_display="${SAMPLE_TEMP_C}°C"
  progress_notify_lines
  echo "Host: ${temp_display}, load ${SAMPLE_LOAD}, $(human_count "${SAMPLE_MEM_AVAIL}") MB free mem, ${SAMPLE_DISK_FREE} disk free"
}

collect_sample
echo "$(render_log_line)" | tee -a "${LOG_PATH}"
notify "Monitoring started: ${UNIT}" "$(render_notify_body)" "low" "hourglass_flowing_sand"

while systemctl is-active --quiet "${UNIT}" 2>/dev/null; do
  sleep "${INTERVAL}"
  collect_sample
  echo "$(render_log_line)" | tee -a "${LOG_PATH}"
  notify "Check-in: ${UNIT}" "$(render_notify_body)" "low" "hourglass_flowing_sand"
done

echo "==> Unit '${UNIT}' is no longer active. Final status:"
final_status="$(systemctl status "${UNIT}" --no-pager 2>&1 || true)"
echo "${final_status}" | tee -a "${LOG_PATH}"
echo "==> Full trend log: ${LOG_PATH}"

compute_progress
if echo "${final_status}" | grep -q "Active: active\|Active: activating"; then
  # Shouldn't happen (the loop above only exits once is-active reports false), but
  # guard against a race rather than send a misleading notification either way.
  notify "Finished (status unclear): ${UNIT}" "Check journalctl -u ${UNIT} directly." "default" "warning"
elif echo "${final_status}" | grep -qE "Active: failed|code=exited, status=[1-9]"; then
  notify "FAILED: ${UNIT}" "$(progress_notify_lines)
See: journalctl -u ${UNIT} --no-pager" "urgent" "x"
else
  notify "Finished: ${UNIT}" "$(progress_notify_lines)" "high" "white_check_mark"
fi
