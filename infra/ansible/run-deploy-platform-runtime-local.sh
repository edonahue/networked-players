#!/usr/bin/env bash
# Local-inventory wrapper; runtime commit and release path are never inferred remotely.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${SCRIPT_DIR}/inventories/local/hosts.yml"
COMMIT="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
RELEASE_DIR="${REPO_ROOT}/local/platform/releases/${COMMIT}"

[[ -f "${RELEASE_DIR}/release.json" ]] || {
  echo "ABORT: no built platform release at ${RELEASE_DIR}; run make platform-build." >&2
  exit 1
}

exec uv run ansible-playbook \
  -i "${INVENTORY}" \
  "${SCRIPT_DIR}/playbooks/deploy-platform-runtime.yml" \
  -e "platform_runtime_commit=${COMMIT}" \
  -e "platform_release_dir_local=${RELEASE_DIR}" \
  "$@"
