#!/usr/bin/env bash
#
# Shared ntfy.sh notification helper. Source this, don't execute it directly:
#   # shellcheck disable=SC1091
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/notify.sh"
#   notify "Title" "message body" [priority] [tags]
#
# Reads NTFY_URL from the environment (see ~/.bashrc; export NTFY_TOPIC and
# NTFY_URL="https://ntfy.sh/$NTFY_TOPIC" there). Degrades gracefully when unset --
# a missing/misconfigured notification must never fail the caller's real work.
#
# priority: ntfy's own scale (min/low/default/high/urgent). tags: ntfy's emoji-tag
# shorthand (e.g. "white_check_mark", "x", "hourglass_flowing_sand").

notify() {
  local title="$1" message="$2" priority="${3:-default}" tags="${4:-}"
  if [[ -z "${NTFY_URL:-}" ]]; then
    echo "(NTFY_URL not set; skipping notification: ${title})" >&2
    return 0
  fi
  curl -fsS \
    -H "Title: ${title}" \
    -H "Priority: ${priority}" \
    ${tags:+-H "Tags: ${tags}"} \
    -d "${message}" \
    "${NTFY_URL}" >/dev/null \
    || echo "WARNING: ntfy notification failed (network issue?): ${title}" >&2
}
