#!/usr/bin/env bash
#
# Build the shared image, start Jupyter (plain, loopback-bound), and deploy
# the Dask scheduler/worker Swarm stack -- both on the coordination host
# only. See docker-stack.dask.yml and docker-compose.jupyter.yml for what
# each piece does and why they use different mechanisms, and README.md for
# the optional build-node worker (docker-compose.dask-worker-remote.yml,
# run separately, directly on that host).
#
# Usage: ./infra/dask/deploy-dask.sh
#        ./infra/dask/deploy-dask.sh --down
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${SCRIPT_DIR}"

ENV_FILE="${REPO_ROOT}/local/dask.env"
IMAGE_TAG="networked-players-dask:local"
STACK_NAME="dask"
OVERLAY_NETWORK="${STACK_NAME}_dask-net"  # Swarm prefixes stack networks with the stack name
JUPYTER_CONTAINER="dask-jupyter-1"        # compose project "dask" + service "jupyter"

if [[ "${1:-}" == "--down" ]]; then
  echo "==> Stopping Jupyter."
  docker compose -f docker-compose.jupyter.yml --env-file "${ENV_FILE}" down || true
  echo "==> Removing the Dask Swarm stack."
  docker stack rm "${STACK_NAME}"

  # `docker stack rm` returns as soon as removal is REQUESTED, not once the
  # network is actually gone -- confirmed live: running dask-up immediately
  # after raced the in-progress teardown ("network dask_dask-net not found"
  # while creating a service that should have recreated it). Wait for the
  # network to actually disappear before this script exits.
  echo "==> Waiting for ${OVERLAY_NETWORK} to finish tearing down (up to 30s)..."
  for _ in $(seq 1 15); do
    docker network inspect "${OVERLAY_NETWORK}" >/dev/null 2>&1 || break
    sleep 2
  done
  if docker network inspect "${OVERLAY_NETWORK}" >/dev/null 2>&1; then
    echo "==> WARNING: ${OVERLAY_NETWORK} still present after 30s -- check 'docker network ls' before re-running dask-up." >&2
  fi
  exit 0
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ABORT: ${ENV_FILE} not found." >&2
  echo "        cp infra/dask/dask.env.example ${ENV_FILE} and edit it." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "${ENV_FILE}"
: "${JUPYTER_TOKEN:?${ENV_FILE} is missing JUPYTER_TOKEN}"
: "${DISCOGS_PROCESSED_DIR:?${ENV_FILE} is missing DISCOGS_PROCESSED_DIR}"
mkdir -p "${DISCOGS_PROCESSED_DIR}"
export JUPYTER_TOKEN DISCOGS_PROCESSED_DIR
export DASK_IMAGE="${IMAGE_TAG}"

# LAN reachability is opt-in, not the default -- set JUPYTER_BIND_IP in
# local/dask.env to a specific address to pin it, or leave it unset to
# auto-detect this host's real LAN interface (same mechanism
# infra/swarm/deploy-jobs-broker.sh already uses; never 0.0.0.0). Set
# JUPYTER_BIND_IP=127.0.0.1 in local/dask.env to opt back out to loopback +
# SSH tunnel only.
if [[ -z "${JUPYTER_BIND_IP:-}" ]]; then
  JUPYTER_BIND_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}')"
  if [[ -z "${JUPYTER_BIND_IP}" ]]; then
    echo "ABORT: could not auto-detect a LAN IP for Jupyter." >&2
    echo "        Set JUPYTER_BIND_IP explicitly in ${ENV_FILE}." >&2
    exit 1
  fi
fi
export JUPYTER_BIND_IP

echo "==> Building ${IMAGE_TAG} (rebuild manually on any other node that runs a dask-worker task -- no shared registry)."
docker build -t "${IMAGE_TAG}" .

echo "==> Deploying the Dask scheduler/worker Swarm stack (coordination host only)."
docker stack deploy -c docker-stack.dask.yml "${STACK_NAME}"

echo "==> Waiting for the ${OVERLAY_NETWORK} overlay network to exist (up to 30s)..."
for _ in $(seq 1 15); do
  docker network inspect "${OVERLAY_NETWORK}" >/dev/null 2>&1 && break
  sleep 2
done
docker network inspect "${OVERLAY_NETWORK}" >/dev/null 2>&1 || {
  echo "ABORT: ${OVERLAY_NETWORK} never appeared -- check 'docker service ls' / 'docker stack ps ${STACK_NAME}'." >&2
  exit 1
}

echo "==> Starting Jupyter (bound to ${JUPYTER_BIND_IP}:8888)."
docker compose -f docker-compose.jupyter.yml --env-file "${ENV_FILE}" up -d

echo "==> Joining Jupyter onto ${OVERLAY_NETWORK} so tcp://dask-scheduler:8786 resolves"
echo "    (same pattern infra/swarm/deploy-portainer-agent.sh uses for Portainer + its Agent)."
docker network connect "${OVERLAY_NETWORK}" "${JUPYTER_CONTAINER}"

echo "==> Done."
if [[ "${JUPYTER_BIND_IP}" == "127.0.0.1" ]]; then
  echo "    Jupyter:        ssh -L 8888:localhost:8888 <this-host>, then open http://localhost:8888"
else
  echo "    Jupyter:        http://${JUPYTER_BIND_IP}:8888  (also reachable via your LAN's mDNS"
  echo "                    hostname, e.g. http://coordination-host.local:8888, if avahi/mDNS is running --"
  echo "                    that's client-side DNS, unrelated to this bind IP)"
fi
echo "    Dask dashboard: ssh -L 8787:localhost:8787 <this-host>, then open http://localhost:8787"
echo "    docker service ls | grep ${STACK_NAME}_"
echo "    Optional build-node worker: see README.md's 'Optional build-node worker' section."
