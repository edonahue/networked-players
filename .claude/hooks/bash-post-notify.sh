#!/bin/bash
# PostToolUse hook (Bash matcher): if the command's real duration (measured against
# the timestamp bash-pre-timer.sh recorded) exceeds LONG_BUILD_THRESHOLD_SECONDS
# (default 120s), send an ntfy notification. Reads NTFY_URL from the environment
# (see ~/.bashrc); silently no-ops if unset -- same graceful-degradation pattern as
# scripts/lib/notify.sh, duplicated here (not sourced) since a hook must be
# self-contained and can't assume the invoking shell's cwd is the repo root. Uses
# python3 (not jq -- confirmed not installed on this host during setup) for JSON
# extraction. Never blocks or fails the actual tool call -- always exits 0.
set +e
THRESHOLD="${LONG_BUILD_THRESHOLD_SECONDS:-120}"
input="$(cat)"
sid="$(printf '%s' "${input}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id", "unknown"))')"
cmd="$(printf '%s' "${input}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", "unknown command"))')"
start_file="/tmp/claude-bash-timers/${sid}"

if [[ -f "${start_file}" ]]; then
  start="$(cat "${start_file}")"
  now="$(date +%s)"
  elapsed=$(( now - start ))
  rm -f "${start_file}"
  if [[ "${elapsed}" -ge "${THRESHOLD}" && -n "${NTFY_URL:-}" ]]; then
    elapsed_human="$(printf '%dm%ds' $((elapsed/60)) $((elapsed%60)))"
    curl -fsS -H "Title: Long command finished (${elapsed_human})" -H "Priority: default" \
      -d "${cmd}" "${NTFY_URL}" >/dev/null 2>&1
  fi
fi
exit 0
