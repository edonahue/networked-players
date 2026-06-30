#!/usr/bin/env bash
#
# One chained entry point for tonight: docker group (best-effort) + swarm
# init + token capture. Safe to re-run.
#
# Usage: ./infra/swarm/bootstrap-manager.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "### 1/2 docker group membership (best-effort, not load-bearing) ###"
"${SCRIPT_DIR}/grant-docker-group.sh"

echo
echo "### 2/2 swarm init + join-token capture ###"
"${SCRIPT_DIR}/init-swarm-manager.sh"

echo
echo "==> Bootstrap complete. Verify: sudo docker info | grep -A3 Swarm"
