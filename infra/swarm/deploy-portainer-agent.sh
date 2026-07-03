#!/usr/bin/env bash
#
# Deploy the Portainer Agent as a global Swarm service (one instance per
# node automatically) and connect the existing plain Portainer container
# onto the same overlay network so it can reach the agent -- see
# docker-compose.portainer-agent.yml's header comment for why this is
# imperative (`docker network connect`) rather than a static compose
# dependency.
#
# Idempotent: safe to re-run. Requires the coordination stack's Portainer
# container to already exist (./deploy-portainer.sh run at least once).
#
# Usage: ./infra/swarm/deploy-portainer-agent.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../scripts/lib/docker-compose.sh"
docker_sudo_setup

STACK_NAME="portainer-agent"
NETWORK_NAME="portainer_agent_net"

echo "==> Checking Docker daemon and Swarm state..."
"${DOCKER[@]}" info >/dev/null
STATE="$("${DOCKER[@]}" info --format '{{.Swarm.LocalNodeState}}')"
if [[ "${STATE}" != "active" ]]; then
  echo "ABORT: this host's Swarm state is '${STATE}', not 'active'." >&2
  exit 1
fi

# Discovered by Compose service label, not a hardcoded name -- confirmed
# live that docker-compose.portainer.yml's container is actually named
# "swarm-portainer-1" (project-name-prefixed, since infra/swarm/'s compose
# files share an inferred project name, already flagged elsewhere in this
# repo), not bare "portainer".
PORTAINER_CONTAINER="$("${DOCKER[@]}" ps --filter "label=com.docker.compose.service=portainer" --format '{{.Names}}' | head -n1)"
if [[ -z "${PORTAINER_CONTAINER}" ]]; then
  echo "ABORT: no running container with compose service label 'portainer' found." >&2
  echo "       Run ./deploy-portainer.sh first." >&2
  exit 1
fi
echo "==> Found Portainer container: ${PORTAINER_CONTAINER}"

echo "==> Deploying the Portainer Agent as a global Swarm service ('${STACK_NAME}')..."
"${DOCKER[@]}" stack deploy -c docker-compose.portainer-agent.yml "${STACK_NAME}"

echo "==> Waiting for the agent network to exist..."
for _ in $(seq 1 10); do
  "${DOCKER[@]}" network inspect "${NETWORK_NAME}" >/dev/null 2>&1 && break
  sleep 2
done
"${DOCKER[@]}" network inspect "${NETWORK_NAME}" >/dev/null 2>&1 || {
  echo "ABORT: network '${NETWORK_NAME}' never appeared after stack deploy." >&2
  exit 1
}

echo "==> Connecting '${PORTAINER_CONTAINER}' onto '${NETWORK_NAME}'..."
if "${DOCKER[@]}" inspect "${PORTAINER_CONTAINER}" --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' | grep -qw "${NETWORK_NAME}"; then
  echo "==> Already connected; nothing to do."
else
  "${DOCKER[@]}" network connect "${NETWORK_NAME}" "${PORTAINER_CONTAINER}"
  echo "==> Connected."
fi

echo
echo "==> Done. In Portainer's UI (Tailscale URL from ./deploy-portainer.sh's output),"
echo "    add/edit the environment to use Agent mode at tasks.agent:9001 to unlock"
echo "    live per-node CPU/RAM/disk stats -- this is a UI step, not automatable here."
echo "==> Verify placement: ${DOCKER[*]} service ps ${STACK_NAME}_agent"
