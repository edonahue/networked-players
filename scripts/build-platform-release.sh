#!/usr/bin/env bash
# Build the dependency-light contracts/platform wheels for an immutable worker release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -n "$(git status --short)" ]]; then
  echo "ABORT: build platform releases only from a clean checkout." >&2
  exit 1
fi

COMMIT="$(git rev-parse HEAD)"
RELEASE_DIR="${REPO_ROOT}/local/platform/releases/${COMMIT}"
WHEELS_DIR="${RELEASE_DIR}/wheels"
mkdir -p "${WHEELS_DIR}"

uv build --package networked-players-contracts --wheel --out-dir "${WHEELS_DIR}"
uv build --package networked-players-platform --wheel --out-dir "${WHEELS_DIR}"
uv build --package networked-players-catalog --wheel --out-dir "${WHEELS_DIR}"

(
  cd "${WHEELS_DIR}"
  sha256sum ./*.whl | sort > "${RELEASE_DIR}/wheel-sha256.txt"
)

cat > "${RELEASE_DIR}/release.json" <<EOF
{
  "schema_version": 1,
  "commit": "${COMMIT}",
  "package_version": "0.1.0"
}
EOF

echo "${RELEASE_DIR}"
