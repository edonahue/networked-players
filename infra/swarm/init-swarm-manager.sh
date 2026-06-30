#!/usr/bin/env bash
#
# Idempotently initialize this host as a Docker Swarm manager and persist the
# worker join token locally for later use (no Pi workers exist yet tonight,
# so capturing the token now means joining them later is a one-liner).
#
# Reads ADVERTISE_ADDR from the environment, or from a git-ignored
# local/swarm.env (copy infra/swarm/swarm.env.example -> local/swarm.env and
# edit it first). Never put the real address in a tracked file.
#
# Usage: ./infra/swarm/init-swarm-manager.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f local/swarm.env ]]; then
  # shellcheck disable=SC1091
  source local/swarm.env
fi
: "${ADVERTISE_ADDR:?Set ADVERTISE_ADDR or create local/swarm.env from infra/swarm/swarm.env.example}"

FLOOR_MB="${FLOOR_MB:-400}"
free_mb=$(( $(df -Pk . | awk 'NR==2{print $4}') / 1024 ))
if (( free_mb < FLOOR_MB )); then
  echo "ABORT: only ${free_mb} MB free (floor: ${FLOOR_MB} MB). Refusing to proceed." >&2
  exit 1
fi
echo "==> Free space OK: ${free_mb} MB free (floor ${FLOOR_MB} MB)."

echo "==> Checking Docker daemon..."
sudo docker info >/dev/null

STATE="$(sudo docker info --format '{{.Swarm.LocalNodeState}}')"
if [[ "${STATE}" == "active" ]]; then
  echo "==> Swarm already active (state=${STATE}); skipping init."
else
  echo "==> Initializing Swarm, advertising on ${ADVERTISE_ADDR}..."
  sudo docker swarm init --advertise-addr "${ADVERTISE_ADDR}"
fi

echo "==> Current node list:"
sudo docker node ls

TOKEN_DIR="local/swarm"
mkdir -p "${TOKEN_DIR}"
echo "==> Persisting join tokens to ${TOKEN_DIR}/ (git-ignored, chmod 600)."
sudo docker swarm join-token -q worker  > "${TOKEN_DIR}/worker-join-token.txt"
sudo docker swarm join-token worker     > "${TOKEN_DIR}/worker-join-command.txt"
sudo docker swarm join-token -q manager > "${TOKEN_DIR}/manager-join-token.txt"
chmod 600 "${TOKEN_DIR}"/*.txt

echo "==> Done. When a Pi worker is ready (its own SSH session):"
echo "    sudo docker swarm join --token \$(cat ${TOKEN_DIR}/worker-join-token.txt) ${ADVERTISE_ADDR}:2377"
echo "    (full command saved in ${TOKEN_DIR}/worker-join-command.txt)"
