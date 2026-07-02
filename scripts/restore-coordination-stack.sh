#!/usr/bin/env bash
#
# Restore the coordination host's Postgres/Redis dev-loop stack from a backup
# made by scripts/backup-coordination-stack.sh. Requires the stack already
# running (./infra/swarm/deploy-coordination.sh) -- this restores INTO the
# live containers, it does not recreate them.
#
# Usage: ./scripts/restore-coordination-stack.sh local/backups/coordination/<timestamp>
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup-dir>" >&2
  echo "Example: $0 local/backups/coordination/20260702T000000Z" >&2
  exit 1
fi
BACKUP_DIR="$(cd "$1" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWARM_DIR="${REPO_ROOT}/infra/swarm"
cd "${SWARM_DIR}"

for f in postgres.sql redis-dump.rdb manifest.json; do
  if [[ ! -f "${BACKUP_DIR}/${f}" ]]; then
    echo "ABORT: ${BACKUP_DIR}/${f} missing -- not a valid backup directory." >&2
    exit 1
  fi
done

if ! id -nG "$(whoami)" | tr ' ' '\n' | grep -qx docker; then
  echo "==> Not in the docker group this session; using sudo."
  DC=(sudo docker compose -f docker-compose.coordination.yml)
else
  DC=(docker compose -f docker-compose.coordination.yml)
fi

running_count="$("${DC[@]}" ps --status running --format '{{.Name}}' 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${running_count}" -ne 2 ]]; then
  echo "ABORT: postgres/redis aren't both running. Run ./infra/swarm/deploy-coordination.sh first." >&2
  exit 1
fi

echo "==> Restoring from ${BACKUP_DIR}"
echo "==> Restoring Postgres (psql < postgres.sql)..."
"${DC[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < "${BACKUP_DIR}/postgres.sql" >/dev/null

echo "==> Restoring Redis (copy dump.rdb, restart to reload)..."
"${DC[@]}" cp "${BACKUP_DIR}/redis-dump.rdb" redis:/data/dump.rdb
"${DC[@]}" restart redis >/dev/null

echo "==> Waiting for both services to report healthy (up to 60s)..."
healthy=0
for _ in $(seq 1 30); do
  healthy_count="$("${DC[@]}" ps 2>/dev/null | grep -c '(healthy)' || true)"
  if [[ "${healthy_count}" -eq 2 ]]; then
    healthy=1
    break
  fi
  sleep 2
done
"${DC[@]}" ps

if [[ "${healthy}" -eq 1 ]]; then
  echo "==> Restore complete; both services healthy."
else
  echo "==> WARNING: not both services reported healthy within 60s; check above output." >&2
  exit 1
fi
