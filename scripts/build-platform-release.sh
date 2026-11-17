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
uv build --package networked-players-research --wheel --out-dir "${WHEELS_DIR}"

(
  cd "${WHEELS_DIR}"
  sha256sum ./*.whl | sort > "${RELEASE_DIR}/wheel-sha256.txt"
)

# ADR 0073: record the runtime digests of this exact checkout (per workload, plus the
# contracts content digest and the uv.lock hash) so a worker can compare what it installed
# with what was built, and `platform-status` can compare it with a later checkout.
DIGESTS_JSON="$(uv run networked-players-platform runtime-digests --repo-root "${REPO_ROOT}")"
COMMIT="${COMMIT}" DIGESTS_JSON="${DIGESTS_JSON}" python3 - "${RELEASE_DIR}/release.json" <<'PY'
import json, os, sys
digests = json.loads(os.environ["DIGESTS_JSON"])
payload = {
    "schema_version": 2,
    "commit": os.environ["COMMIT"],
    "package_version": "0.1.0",
    "uv_lock_sha256": digests["uv_lock_sha256"],
    "runtime_digests": digests["runtime_digests"],
    "contracts_digest": digests["contracts_digest"],
}
with open(sys.argv[1], "w") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

echo "${RELEASE_DIR}"
