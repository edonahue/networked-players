#!/usr/bin/env bash
#
# One-time migration: move the coordination stack's postgres-data/redis-data
# Docker volumes off the 28GB eMMC onto the NVMe mounted at /mnt/data, closing
# the revisit trigger left by docs/decisions/0010-coordination-stack-ahead-of-nvme.md
# ("must be migrated (not simply recreated) onto the NVMe once it's attached, or
# accumulated state is lost"). See docs/decisions/0013-nvme-storage-layout.md.
#
# What this does, in order (order matters -- Docker's local driver only applies
# driver_opts at volume *creation*, so the OLD plain volume must be gone before
# `up` recreates it, or docker-compose.coordination.yml's new bind config is
# silently ignored):
#   1. Stop the stack (`down`, does not remove volumes).
#   2. Find the real (project-prefixed) names of the existing postgres-data/
#      redis-data volumes via `docker volume ls` -- not assumed.
#   3. Copy each volume's contents to /mnt/data/docker-volumes/<key>/ with a
#      throwaway container (preserves ownership/permissions Postgres needs).
#   4. Remove the old volume.
#   5. Bring the stack back up against the already-edited compose file, which
#      now binds each named volume to its /mnt/data/docker-volumes/<key> path.
#
# Safe to re-run: a volume with no matching /mnt/data destination content is
# skipped with a message, not silently re-copied over newer data.
#
# Usage: ./infra/swarm/migrate-coordination-volumes-to-nvme.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

NVME_ROOT="/mnt/data"
VOLUMES_ROOT="${NVME_ROOT}/docker-volumes"

if ! mountpoint -q "${NVME_ROOT}"; then
  echo "ABORT: ${NVME_ROOT} is not a mountpoint. Attach and mount the NVMe first" >&2
  echo "       (see docs/decisions/0013-nvme-storage-layout.md)." >&2
  exit 1
fi

if ! id -nG "$(whoami)" | tr ' ' '\n' | grep -qx docker; then
  echo "==> Not in the docker group this session; using sudo."
  DOCKER=(sudo docker)
  DC=(sudo docker compose -f docker-compose.coordination.yml)
else
  DOCKER=(docker)
  DC=(docker compose -f docker-compose.coordination.yml)
fi

sudo mkdir -p "${VOLUMES_ROOT}"
sudo chown "$(id -u)":"$(id -g)" "${VOLUMES_ROOT}"
sudo chmod 755 "${VOLUMES_ROOT}"

echo "==> Stopping the coordination stack (volumes are preserved)..."
"${DC[@]}" down

migrate_one() {
  local key="$1" # e.g. "postgres-data"
  local dest="${VOLUMES_ROOT}/${key}"
  local old_vol
  old_vol="$("${DOCKER[@]}" volume ls --format '{{.Name}}' | grep -E "(^|_)${key}\$" | head -1 || true)"

  if [[ -z "${old_vol}" ]]; then
    echo "==> No existing volume found matching '${key}'; nothing to migrate (already done, or never created)."
    return
  fi

  if [[ -d "${dest}" ]] && [[ -n "$(ls -A "${dest}" 2>/dev/null)" ]]; then
    echo "==> ${dest} already has content; skipping copy for '${key}' (assuming already migrated)."
  else
    echo "==> Copying volume '${old_vol}' -> ${dest} ..."
    mkdir -p "${dest}"
    "${DOCKER[@]}" run --rm \
      -v "${old_vol}:/from:ro" \
      -v "${dest}:/to" \
      alpine sh -c "cd /from && cp -a . /to"
  fi

  echo "==> Removing old eMMC-backed volume '${old_vol}'..."
  "${DOCKER[@]}" volume rm "${old_vol}"
}

migrate_one postgres-data
migrate_one redis-data

echo "==> Bringing the stack back up (now bind-mounted onto ${VOLUMES_ROOT})..."
"${DC[@]}" up -d

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
  echo "==> Both services healthy on the new NVMe-backed volumes."
else
  echo "==> WARNING: not both services reported healthy within 60s; check above output." >&2
fi

echo "==> Verify: find ${VOLUMES_ROOT} -maxdepth 2"
echo "==> Verify loopback-only binding: ss -tln | grep -E '5432|6379'"
