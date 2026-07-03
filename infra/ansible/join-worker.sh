#!/usr/bin/env bash
#
# Guarded, single-worker Swarm join -- thin wrapper so the pasteable command
# is short (one word: the worker's inventory alias) rather than a long
# multi-flag line that's easy to mangle when pasted from a phone. Internally
# equivalent to:
#   CONFIRM=yes ARGS="--limit <worker> --ask-become-pass" make cluster-swarm-join
#
# Usage: ./infra/ansible/join-worker.sh <worker-alias>
#   ./infra/ansible/join-worker.sh worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORKER="${1:?Usage: $0 <worker-alias>  (e.g. worker-01)}"

exec "${SCRIPT_DIR}/run-swarm-join-local.sh" \
  -e confirm_swarm_join=true \
  --ask-become-pass \
  --limit "${WORKER}"
