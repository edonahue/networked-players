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
    # Summarize, don't dump the raw command -- a multi-line heredoc/script
    # (common for anything long-running enough to trip this threshold) was
    # showing up verbatim as the push-notification body, unreadable on a
    # phone lock screen. Skip leading boilerplate (cd/comments/blank lines)
    # rather than blindly taking line 1 -- confirmed live that a plain
    # "first line" summary just showed "cd /path/to/repo" for a command
    # that led with a directory change, telling you nothing about what
    # actually ran. Falls back to the true first line if every line looks
    # like boilerplate.
    line_count="$(printf '%s' "${cmd}" | wc -l | tr -d ' ')"
    summary_line="$(printf '%s\n' "${cmd}" \
      | grep -vE '^[[:space:]]*(cd |#|$|[A-Za-z_][A-Za-z0-9_]*=)' | head -1)"
    [[ -z "${summary_line}" ]] && summary_line="$(printf '%s' "${cmd}" | head -1)"
    summary_line="$(printf '%s' "${summary_line}" | cut -c1-120)"
    summary="${summary_line}"
    if [[ "${line_count}" -gt 1 ]]; then
      summary="${summary} (+${line_count} lines total)"
    elif [[ "${#summary_line}" -eq 120 ]]; then
      summary="${summary}..."
    fi
    curl -fsS -H "Title: Long command finished (${elapsed_human})" -H "Priority: default" \
      -d "${summary}" "${NTFY_URL}" >/dev/null 2>&1
  fi
fi
exit 0
