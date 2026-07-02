#!/usr/bin/env bash
#
# Back up this Docker Swarm manager's CA/raft state (/var/lib/docker/swarm).
# There is no logical-export equivalent for the raft store the way pg_dump is
# for Postgres, so this briefly stops the Docker daemon to copy it safely --
# see docs/decisions/0016-state-backup-and-recovery.md.
#
# WARNING: stopping dockerd also stops the coordination-stack containers
# (Postgres/Redis/Portainer). Per ADR 0014's own real incident,
# `restart: unless-stopped` does NOT reliably bring them back on its own --
# this script automatically re-runs deploy-coordination.sh/deploy-portainer.sh
# afterward, but expect a real, brief outage of those services while it runs.
#
# Requires sudo. Usage: ./scripts/backup-swarm-manager-state.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWARM_DIR="${REPO_ROOT}/infra/swarm"
cd "${REPO_ROOT}"

echo "==> This will briefly stop Docker (and the coordination stack with it)."
echo "    Press Ctrl+C now to abort, or wait 5s to continue..."
sleep 5

echo "==> Confirming this host is an active Swarm manager..."
STATE="$(sudo docker info --format '{{.Swarm.LocalNodeState}}')"
IS_MANAGER="$(sudo docker info --format '{{.Swarm.ControlAvailable}}')"
if [[ "${STATE}" != "active" || "${IS_MANAGER}" != "true" ]]; then
  echo "ABORT: this host isn't an active Swarm manager (state=${STATE}, manager=${IS_MANAGER})." >&2
  exit 1
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="local/backups/swarm-manager/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"

echo "==> Stopping Docker..."
sudo systemctl stop docker

echo "==> Archiving /var/lib/docker/swarm..."
sudo tar -czf "${BACKUP_DIR}/swarm-state.tar.gz" -C /var/lib/docker/swarm .
sudo chown "$(id -u):$(id -g)" "${BACKUP_DIR}/swarm-state.tar.gz"
chmod 600 "${BACKUP_DIR}/swarm-state.tar.gz"
archive_bytes="$(stat -c '%s' "${BACKUP_DIR}/swarm-state.tar.gz")"
echo "    wrote ${BACKUP_DIR}/swarm-state.tar.gz (${archive_bytes} bytes)"

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
  exit 1
fi

echo "==> Re-deploying the coordination stack (expected -- see ADR 0014/0016)..."
"${SWARM_DIR}/deploy-coordination.sh"
"${SWARM_DIR}/deploy-portainer.sh"

cat > "${BACKUP_DIR}/manifest.json" <<JSON
{
  "backup_timestamp": "${TIMESTAMP}",
  "archive_bytes": ${archive_bytes},
  "method": "systemctl stop docker; tar /var/lib/docker/swarm; systemctl start docker"
}
JSON

echo "==> Confirming Swarm manager health post-backup..."
sudo docker node ls

echo "==> Done: ${BACKUP_DIR}/swarm-state.tar.gz"
echo "    Verify contents with: tar -tzf ${BACKUP_DIR}/swarm-state.tar.gz"
