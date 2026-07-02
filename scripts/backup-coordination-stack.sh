#!/usr/bin/env bash
#
# Back up the coordination host's Postgres/Redis dev-loop stack
# (infra/swarm/docker-compose.coordination.yml) with logical dumps, not raw
# volume tars: `pg_dump` (transactionally consistent) and Redis `BGSAVE`
# (Redis's own async snapshot), both taken through `docker compose exec`/`cp`.
# No downtime, no root needed -- see docs/decisions/0016-state-backup-and-recovery.md.
#
# Requires the stack already running (./infra/swarm/deploy-coordination.sh).
#
# Usage: ./scripts/backup-coordination-stack.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SWARM_DIR="${REPO_ROOT}/infra/swarm"
cd "${SWARM_DIR}"

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

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${REPO_ROOT}/local/backups/coordination/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"

echo "==> Dumping Postgres (pg_dump, using the container's own POSTGRES_USER/POSTGRES_DB)..."
"${DC[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "${BACKUP_DIR}/postgres.sql"
postgres_bytes="$(stat -c '%s' "${BACKUP_DIR}/postgres.sql")"
echo "    wrote ${BACKUP_DIR}/postgres.sql (${postgres_bytes} bytes)"

echo "==> Triggering Redis BGSAVE and waiting for it to complete..."
before_save="$("${DC[@]}" exec -T redis redis-cli LASTSAVE | tr -d '\r')"
"${DC[@]}" exec -T redis redis-cli BGSAVE >/dev/null
saved=0
for _ in $(seq 1 30); do
  after_save="$("${DC[@]}" exec -T redis redis-cli LASTSAVE | tr -d '\r')"
  if [[ "${after_save}" != "${before_save}" ]]; then
    saved=1
    break
  fi
  sleep 1
done
if [[ "${saved}" -ne 1 ]]; then
  echo "ABORT: Redis BGSAVE did not complete within 30s." >&2
  exit 1
fi
"${DC[@]}" cp redis:/data/dump.rdb "${BACKUP_DIR}/redis-dump.rdb"
redis_bytes="$(stat -c '%s' "${BACKUP_DIR}/redis-dump.rdb")"
echo "    wrote ${BACKUP_DIR}/redis-dump.rdb (${redis_bytes} bytes)"

postgres_image="$("${DC[@]}" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^postgres' || echo unknown)"
redis_image="$("${DC[@]}" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^redis' || echo unknown)"
cat > "${BACKUP_DIR}/manifest.json" <<JSON
{
  "backup_timestamp": "${TIMESTAMP}",
  "postgres_image": "${postgres_image}",
  "redis_image": "${redis_image}",
  "postgres_dump_bytes": ${postgres_bytes},
  "redis_dump_bytes": ${redis_bytes},
  "method": "pg_dump + redis BGSAVE via docker compose exec/cp, no downtime"
}
JSON

chmod -R 600 "${BACKUP_DIR}"/*
chmod 700 "${BACKUP_DIR}"

echo "==> Done: ${BACKUP_DIR}"
echo "    Restore with: ./scripts/restore-coordination-stack.sh ${BACKUP_DIR}"
