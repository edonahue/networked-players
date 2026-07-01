#!/bin/bash
# PreToolUse hook (Bash matcher): records a start timestamp keyed by session_id,
# read back by bash-post-notify.sh to compute a Bash command's real duration for
# the long-build ntfy notification. Uses python3 (not jq -- confirmed not installed
# on this host during setup) for JSON extraction; python3 is present system-wide.
set -euo pipefail
input="$(cat)"
sid="$(printf '%s' "${input}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id", "unknown"))')"
mkdir -p /tmp/claude-bash-timers
date +%s > "/tmp/claude-bash-timers/${sid}"
