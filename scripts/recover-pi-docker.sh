#!/usr/bin/env bash
#
# One-off recovery for Pi workers whose Docker daemon is stuck `failed` after a
# power outage. Root cause (diagnosed 2026-07-09): after the outage, dockerd
# started before the LAN route to the Swarm manager was up, its cluster
# component failed with "network is unreachable", and systemd gave up after the
# default start-limit (3 quick retries) -- leaving Docker `failed` even though
# the network recovered seconds later. This clears the failure counter and
# starts docker, which rejoins the Swarm now that the manager is reachable.
#
# Needs sudo ON THE PIs -- run this yourself; Ansible prompts for the BECOME
# (sudo) password once. Idempotent: reset-failed + start are no-ops on an
# already-running daemon, so re-running is safe.
#
# Durable prevention (a docker.service restart-limit drop-in) is in
# infra/ansible/playbooks/harden-workers.yml -- `make harden-workers
# ARGS=--ask-become-pass` installs it and also recovers a currently-failed
# daemon. This script is the quick, targeted "fix it right now" path.
#
# Usage (from anywhere in the repo):
#   ./scripts/recover-pi-docker.sh              # all pi_workers
#   ./scripts/recover-pi-docker.sh worker-01    # a single host
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANSIBLE_DIR="${REPO_ROOT}/infra/ansible"
INVENTORY="${ANSIBLE_DIR}/inventories/local/hosts.yml"
LIMIT="${1:-pi_workers}"

[[ -f "${INVENTORY}" ]] || { echo "ABORT: no local inventory at ${INVENTORY}" >&2; exit 1; }

echo "==> Recovering Docker on '${LIMIT}' -- you will be prompted for the sudo (BECOME) password."
cd "${ANSIBLE_DIR}"
uv run ansible "${LIMIT}" -i "${INVENTORY}" --become --ask-become-pass \
  -m shell -a "systemctl reset-failed docker 2>/dev/null; systemctl start docker; sleep 2; systemctl is-active docker"

echo
echo "==> Each host above should report 'active'. Confirm the Swarm rejoin on the manager:"
echo "      docker node ls      # the three Pi workers should return to Status=Ready"
