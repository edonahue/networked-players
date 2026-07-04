#!/usr/bin/env bash
#
# rsync fallback for replicating a dataset to a worker's local cache (ADR
# 0025). The primary mechanism is the HTTP puller (dataset_fetch.py, driven
# by make replicate-x86/replicate-pi over the catalog-data server, ADR
# 0024); this script is the delta-efficient alternative for a large bulk
# transfer over SSH when the HTTP pull is impractically slow -- x86 workers
# only, never Pi's (Pi's always go through the guarded, one-hop-only
# ansible playbook, replicate-dataset-pi.yml).
#
# Runs FROM the master/coordination host, which already has local/processed/
# and (per the fleet's onboarding) SSH access to its workers. Master stays
# authoritative; the remote copy this produces is a disposable replica --
# rsync itself does not write a .verified.json marker, so ALWAYS follow up
# with a verify-only pass (printed below) before anything treats the remote
# copy as trustworthy.
#
# Usage:
#   ./scripts/replicate-rsync.sh <dataset> <snapshot> <ssh-target> <remote-cache-root>
#   ./scripts/replicate-rsync.sh discogs 20260601 x86-worker.example.internal \
#     /home/operator/networked-players-cache
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "ABORT: do not run this script with sudo." >&2
  exit 1
fi

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <dataset> <snapshot> <ssh-target> <remote-cache-root>" >&2
  exit 1
fi

DATASET="$1"
SNAPSHOT="$2"
SSH_TARGET="$3"
REMOTE_CACHE_ROOT="$4"

case "${DATASET}" in
  discogs | discogs-onehop | discogs-masters) ;;
  *)
    echo "ABORT: unknown dataset '${DATASET}' (expected discogs, discogs-onehop, or discogs-masters)" >&2
    exit 1
    ;;
esac

if ! [[ "${SNAPSHOT}" =~ ^[0-9]{8}$ ]]; then
  echo "ABORT: snapshot must be YYYYMMDD, got '${SNAPSHOT}'" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_DATASET_ROOT="${REPO_ROOT}/local/processed/${DATASET}/snapshot=${SNAPSHOT}"
REMOTE_FINAL="${REMOTE_CACHE_ROOT}/${DATASET}/snapshot=${SNAPSHOT}"
REMOTE_PARTIAL="${REMOTE_FINAL}.rsync-partial"

if [[ ! -d "${LOCAL_DATASET_ROOT}" ]]; then
  echo "ABORT: no local dataset at ${LOCAL_DATASET_ROOT}" >&2
  exit 1
fi

echo "Syncing ${LOCAL_DATASET_ROOT}/ -> ${SSH_TARGET}:${REMOTE_PARTIAL}/ ..."
rsync -av --delete "${LOCAL_DATASET_ROOT}/" "${SSH_TARGET}:${REMOTE_PARTIAL}/"

echo "Swapping into place at ${REMOTE_FINAL} ..."
ssh "${SSH_TARGET}" "rm -rf '${REMOTE_FINAL}' && mv '${REMOTE_PARTIAL}' '${REMOTE_FINAL}'"

cat <<EOF

Synced. This copy has NOT been verified yet -- rsync alone doesn't write the
.verified.json marker that "validated local cache" requires (ADR 0025).
Verify it now:

  make replicate-x86 DATASET=${DATASET} SNAPSHOT=${SNAPSHOT} \\
    ARGS='-e verify_only=true --limit ${SSH_TARGET}'
EOF
