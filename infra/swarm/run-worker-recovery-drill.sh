#!/usr/bin/env bash
#
# One-worker drain/remove/rejoin recovery drill (docs/BUILD_PLAN.md
# Milestone 2). Deliberately separate from onboarding/joining -- this is
# destructive topology work on a live cluster and gets its own explicit
# gate, run only after the fleet is otherwise stable and smoke-tested.
#
# Takes the worker's ANSIBLE inventory alias (e.g. worker-01), not the
# node's actual Docker Swarm hostname (whatever `hostname` reports on that
# machine) -- Ansible and Docker each have their own naming, so the script
# discovers the real Docker node hostname itself over SSH rather than
# requiring the operator to know both.
#
# Real Docker Swarm behavior this script accounts for: `docker node rm`
# refuses a node that's still Ready/connected, even after draining -- the
# node's own daemon has to actually leave the Swarm first (`docker swarm
# leave`, run on the worker itself), otherwise the manager and the worker
# end up disagreeing about membership and a later rejoin can silently no-op
# instead of really re-joining.
#
# Does NOT auto-rejoin. Prints the exact one-liner to rejoin via the
# existing guarded swarm-join playbook so the operator stays in the loop
# for that half too, same as every other join in this repo.
#
# Usage: ./infra/swarm/run-worker-recovery-drill.sh --yes-i-am-sure --worker <ansible-alias>
set -euo pipefail

WORKER=""
CONFIRMED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes-i-am-sure) CONFIRMED=1; shift ;;
    --worker) WORKER="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ "${CONFIRMED}" -ne 1 || -z "${WORKER}" ]]; then
  echo "Usage: $0 --yes-i-am-sure --worker <ansible-alias>  (e.g. worker-01)" >&2
  echo "This drains and REMOVES the given worker from the Swarm. Requires both flags." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ANSIBLE_INV="${REPO_ROOT}/infra/ansible/inventories/local/hosts.yml"

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

echo "==> Checking Docker daemon and Swarm state (on the manager)..."
sudo docker info >/dev/null
STATE="$(sudo docker info --format '{{.Swarm.LocalNodeState}}')"
if [[ "${STATE}" != "active" ]]; then
  echo "ABORT: this host's Swarm state is '${STATE}', not 'active'." >&2
  exit 1
fi

if ! sudo docker node inspect "${NODE_NAME}" >/dev/null 2>&1; then
  echo "ABORT: '${NODE_NAME}' is not a known Swarm node (check 'sudo docker node ls')." >&2
  exit 1
fi

ROLE="$(sudo docker node inspect --format '{{.Spec.Role}}' "${NODE_NAME}")"
if [[ "${ROLE}" != "worker" ]]; then
  echo "ABORT: '${NODE_NAME}' has role '${ROLE}', not 'worker'. Refusing to touch a manager." >&2
  exit 1
fi

echo "==> Current state of '${NODE_NAME}':"
sudo docker node inspect --format '{{.Status.State}} {{.Spec.Availability}}' "${NODE_NAME}"

echo "==> Draining '${NODE_NAME}' (existing tasks will be rescheduled to other workers)..."
sudo docker node update --availability drain "${NODE_NAME}" >/dev/null

echo "==> Waiting for tasks to clear off '${NODE_NAME}'..."
remaining=0
for _ in $(seq 1 20); do
  remaining="$(sudo docker node ps "${NODE_NAME}" --filter desired-state=running --format '{{.ID}}' | wc -l | tr -d ' ')"
  if [[ "${remaining}" -eq 0 ]]; then
    break
  fi
  sleep 3
done
echo "==> Tasks remaining on '${NODE_NAME}': ${remaining}"

echo "==> Telling '${WORKER}' to leave the Swarm on its own side (required before"
echo "    the manager will let it be removed cleanly)..."
ansible -i "${ANSIBLE_INV}" "${WORKER}" -m command -a "docker swarm leave" --become --ask-become-pass

echo "==> Waiting for the manager to detect '${NODE_NAME}' as down (heartbeat"
echo "    timeout, not instant -- polling rather than assuming)..."
node_status="unknown"
for _ in $(seq 1 20); do
  node_status="$(sudo docker node inspect --format '{{.Status.State}}' "${NODE_NAME}")"
  if [[ "${node_status}" == "down" ]]; then
    break
  fi
  sleep 3
done
echo "==> '${NODE_NAME}' status: ${node_status}"

echo "==> Removing '${NODE_NAME}' from the Swarm (manager-side record)..."
sudo docker node rm "${NODE_NAME}"

echo
echo "==> Drain + leave + remove complete. Current node list:"
sudo docker node ls

echo
echo "==> To rejoin '${WORKER}' cleanly via the existing guarded join playbook, run:"
echo "    ./infra/ansible/join-worker.sh ${WORKER}"
