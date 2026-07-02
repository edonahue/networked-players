#!/usr/bin/env bash
#
# Restore this Docker Swarm manager's CA/raft state from a backup made by
# scripts/backup-swarm-manager-state.sh. THIS REPLACES THE MANAGER'S IDENTITY
# -- it is the single most destructive script in this repository. The
# current state is moved (not deleted) to /var/lib/docker/swarm.bak first, so
# a bad restore isn't unrecoverable, but this still stops Docker and the
# coordination stack while it runs. See docs/decisions/0016-state-backup-and-recovery.md.
#
# Requires sudo and the explicit --yes-i-am-sure flag.
# Usage: ./scripts/restore-swarm-manager-state.sh <backup-file> --yes-i-am-sure
set -euo pipefail

if [[ $# -ne 2 || "$2" != "--yes-i-am-sure" ]]; then
  echo "This REPLACES the Swarm manager's CA/raft state -- the only manager this" >&2
  echo "cluster has. It stops Docker (and the coordination stack) while it runs." >&2
  echo >&2
  echo "Usage: $0 <backup-file> --yes-i-am-sure" >&2
  echo "Example: $0 local/backups/swarm-manager/20260702T000000Z/swarm-state.tar.gz --yes-i-am-sure" >&2
  exit 1
fi
BACKUP_FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWARM_DIR="${REPO_ROOT}/infra/swarm"
cd "${REPO_ROOT}"

if [[ ! -f "${BACKUP_FILE}" ]]; then
  echo "ABORT: ${BACKUP_FILE} not found." >&2
  exit 1
fi
echo "==> Verifying archive integrity (tar -tzf)..."
tar -tzf "${BACKUP_FILE}" >/dev/null

echo "==> About to replace /var/lib/docker/swarm from ${BACKUP_FILE}."
echo "    Current state will be preserved at /var/lib/docker/swarm.bak, not deleted."
echo "    Press Ctrl+C now to abort, or wait 5s to continue..."
sleep 5

echo "==> Stopping Docker..."
sudo systemctl stop docker

if [[ -d /var/lib/docker/swarm.bak ]]; then
  echo "ABORT: /var/lib/docker/swarm.bak already exists from a previous restore." >&2
  echo "    Move or remove it first, then re-run this script." >&2
  sudo systemctl start docker
  exit 1
fi

echo "==> Preserving current state at /var/lib/docker/swarm.bak..."
sudo mv /var/lib/docker/swarm /var/lib/docker/swarm.bak

echo "==> Extracting backup into /var/lib/docker/swarm..."
sudo mkdir -p /var/lib/docker/swarm
sudo tar -xzf "${BACKUP_FILE}" -C /var/lib/docker/swarm

echo "==> Restarting Docker..."
sudo systemctl start docker

echo "==> Waiting for the Docker socket to respond (up to 30s)..."
ready=0
for _ in $(seq 1 15); do
  if sudo docker info >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "${ready}" -ne 1 ]]; then
  echo "ABORT: Docker did not come back within 30s. Check 'sudo systemctl status docker'." >&2
  echo "    The pre-restore state is still at /var/lib/docker/swarm.bak." >&2
  exit 1
fi

echo "==> Re-deploying the coordination stack (expected -- see ADR 0014/0016)..."
"${SWARM_DIR}/deploy-coordination.sh"
"${SWARM_DIR}/deploy-portainer.sh"

echo "==> Confirming Swarm manager health post-restore..."
sudo docker node ls

echo "==> Done. Pre-restore state kept at /var/lib/docker/swarm.bak -- remove it"
echo "    manually once you've confirmed the restore is good."
