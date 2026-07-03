#!/usr/bin/env bash
#
# Thin wrapper over run-worker-recovery-drill.sh so the pasteable command is
# short (one word: the worker's inventory alias). Equivalent to:
#   ./infra/swarm/run-worker-recovery-drill.sh --yes-i-am-sure --worker <alias>
#
# Usage: ./infra/swarm/drill-worker.sh <worker-alias>
#   ./infra/swarm/drill-worker.sh worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WORKER="${1:?Usage: $0 <worker-alias>  (e.g. worker-01)}"

exec "${SCRIPT_DIR}/run-worker-recovery-drill.sh" --yes-i-am-sure --worker "${WORKER}"
