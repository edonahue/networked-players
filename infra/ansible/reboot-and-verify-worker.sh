#!/usr/bin/env bash
#
# Real resilience test: reboot one worker and confirm it rejoins the Swarm
# with zero manual intervention -- the actual answer to "if a worker goes
# down, can it reconnect automatically," not just an inference from
# systemctl-is-enabled/Swarm-state-on-disk config.
#
# Captures the worker's current Swarm node ID first, reboots it, waits for
# SSH to come back, then polls the manager's `docker node ls` for that SAME
# node ID to return to Ready/Active -- a genuinely different node ID after
# reboot would mean it did NOT auto-rejoin (e.g. Docker didn't start on
# boot, or Swarm state wasn't persisted), which this script treats as a
# real failure, not a false positive.
#
# Takes the worker's ANSIBLE inventory alias (e.g. worker-01), same
# convention as join-worker.sh/drill-worker.sh.
#
# Usage: ./infra/ansible/reboot-and-verify-worker.sh <ansible-alias>
#   ./infra/ansible/reboot-and-verify-worker.sh worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

WORKER="${1:?Usage: $0 <ansible-alias>  (e.g. worker-01)}"
ANSIBLE_INV="inventories/local/hosts.yml"

if [[ ! -f "${ANSIBLE_INV}" ]]; then
  echo "ABORT: ${ANSIBLE_INV} not found." >&2
  exit 1
fi

echo "==> Discovering '${WORKER}'s real Docker Swarm node hostname over SSH..."
NODE_NAME="$(ansible -i "${ANSIBLE_INV}" "${WORKER}" -m command -a hostname 2>/dev/null | tail -n1 | tr -d '[:space:]')"
if [[ -z "${NODE_NAME}" ]]; then
  echo "ABORT: could not determine '${WORKER}'s hostname via Ansible. Is it reachable?" >&2
  exit 1
fi
echo "==> '${WORKER}' is Docker Swarm node '${NODE_NAME}'."

echo "==> Recording the node ID BEFORE reboot (on the manager)..."
NODE_ID_BEFORE="$(sudo docker node inspect --format '{{.ID}}' "${NODE_NAME}")"
STATE_BEFORE="$(sudo docker node inspect --format '{{.Status.State}}' "${NODE_NAME}")"
echo "==> Before: ID=${NODE_ID_BEFORE} state=${STATE_BEFORE}"

echo "==> Rebooting '${WORKER}' (real, brief downtime for this one worker)..."
ansible -i "${ANSIBLE_INV}" "${WORKER}" -m reboot -a "reboot_timeout=180" --become --ask-become-pass

echo "==> Reboot confirmed complete (SSH came back). Waiting a moment for"
echo "    dockerd to finish starting and rejoin the Swarm..."
sleep 15

echo "==> Polling the manager for '${NODE_NAME}' to return to Ready/Active..."
attempt=0
node_id_after=""
state_after=""
availability_after=""
for attempt in $(seq 1 20); do
  node_id_after="$(sudo docker node inspect --format '{{.ID}}' "${NODE_NAME}" 2>/dev/null || true)"
  state_after="$(sudo docker node inspect --format '{{.Status.State}}' "${NODE_NAME}" 2>/dev/null || true)"
  availability_after="$(sudo docker node inspect --format '{{.Spec.Availability}}' "${NODE_NAME}" 2>/dev/null || true)"
  if [[ "${state_after}" == "ready" && "${availability_after}" == "active" ]]; then
    break
  fi
  sleep 5
done

echo
echo "==> After: ID=${node_id_after} state=${state_after} availability=${availability_after}"

if [[ "${state_after}" != "ready" || "${availability_after}" != "active" ]]; then
  echo "FAILED: '${NODE_NAME}' did not return to Ready/Active after reboot (last seen:" >&2
  echo "        state=${state_after} availability=${availability_after}). Manual intervention needed." >&2
  exit 1
fi

if [[ "${node_id_after}" != "${NODE_ID_BEFORE}" ]]; then
  echo "FAILED: node ID changed (${NODE_ID_BEFORE} -> ${node_id_after}) -- this means it did NOT" >&2
  echo "        automatically rejoin the ORIGINAL Swarm membership; something re-created it instead." >&2
  exit 1
fi

echo
echo "==> PASSED: '${NODE_NAME}' automatically rejoined the Swarm after reboot, same node ID,"
echo "    no manual join required."
