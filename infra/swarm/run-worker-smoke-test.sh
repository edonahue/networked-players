#!/usr/bin/env bash
#
# Deploy a harmless, self-cleaning multi-arch smoke service to confirm every
# joined worker can pull an image and run a task -- and that nothing lands
# on the manager. Plain `sudo docker` (Swarm service commands, not Ansible),
# operator-run.
#
# Real audit finding fixed here: the runbook this replaced
# (infra/swarm/README.md's old snippet) combined `--mode global` with an
# explicit `--replicas 1`, which is invalid/contradictory (--replicas only
# applies to replicated mode) and had no placement constraint at all, so it
# would have scheduled onto the manager too. This script uses global mode
# alone, constrained to workers, with no published port, and removes itself
# even on a partial failure.
#
# Usage: ./infra/swarm/run-worker-smoke-test.sh [image]   (default: traefik/whoami)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

IMAGE="${1:-traefik/whoami}"
SERVICE="smoke-$(date +%s)"
TIMEOUT_S="${TIMEOUT_S:-90}"

echo "==> Checking Docker daemon and Swarm state..."
sudo docker info >/dev/null
STATE="$(sudo docker info --format '{{.Swarm.LocalNodeState}}')"
if [[ "${STATE}" != "active" ]]; then
  echo "ABORT: this host's Swarm state is '${STATE}', not 'active'." >&2
  exit 1
fi

WORKER_COUNT="$(sudo docker node ls --filter role=worker --format '{{.ID}}' | wc -l | tr -d ' ')"
if [[ "${WORKER_COUNT}" -eq 0 ]]; then
  echo "ABORT: no worker nodes found in 'docker node ls'. Join at least one first." >&2
  exit 1
fi
echo "==> ${WORKER_COUNT} worker node(s) found."

echo "==> Verifying '${IMAGE}' supports aarch64 before deploying (real audit finding:"
echo "    don't assume an image is multi-arch)..."
if ! sudo docker manifest inspect "${IMAGE}" 2>/dev/null | grep -q '"architecture": "arm64"'; then
  echo "ABORT: '${IMAGE}' manifest does not list an arm64 platform (or manifest" >&2
  echo "       inspection failed). Refusing to deploy to Pi 3B workers." >&2
  exit 1
fi
echo "==> ${IMAGE} confirmed multi-arch (includes arm64)."

cleanup() {
  echo "==> Removing smoke service '${SERVICE}' (cleanup, runs even on failure)..."
  sudo docker service rm "${SERVICE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Creating global-mode smoke service '${SERVICE}' (workers only, no published port)..."
sudo docker service create \
  --name "${SERVICE}" \
  --mode global \
  --constraint 'node.role==worker' \
  "${IMAGE}" >/dev/null

echo "==> Waiting up to ${TIMEOUT_S}s for ${WORKER_COUNT} Running task(s)..."
deadline=$((SECONDS + TIMEOUT_S))
running=0
while (( SECONDS < deadline )); do
  running="$(sudo docker service ps "${SERVICE}" --filter desired-state=running --format '{{.CurrentState}}' | grep -c '^Running' || true)"
  if [[ "${running}" -ge "${WORKER_COUNT}" ]]; then
    break
  fi
  sleep 3
done

echo
echo "==> Task report:"
sudo docker service ps "${SERVICE}" --no-trunc

if [[ "${running}" -lt "${WORKER_COUNT}" ]]; then
  echo
  echo "FAILED: only ${running}/${WORKER_COUNT} task(s) reached Running within ${TIMEOUT_S}s." >&2
  echo "        Check the task report above for pull errors vs. scheduling errors vs. just-slow." >&2
  exit 1
fi

echo
echo "==> Confirming no task landed on the manager..."
manager_hits=0
while IFS= read -r node_name; do
  [[ -z "${node_name}" ]] && continue
  role="$(sudo docker node inspect --format '{{.Spec.Role}}' "${node_name}")"
  if [[ "${role}" == "manager" ]]; then
    manager_hits=$((manager_hits + 1))
  fi
done < <(sudo docker service ps "${SERVICE}" --filter desired-state=running --format '{{.Node}}' | sort -u)

if [[ "${manager_hits}" -gt 0 ]]; then
  echo "FAILED: ${manager_hits} task(s) landed on a manager node." >&2
  exit 1
fi

echo "==> Confirmed: ${running}/${WORKER_COUNT} Running, all on workers, none on the manager."
echo "==> Smoke test PASSED. The service will be removed now (see cleanup above)."
