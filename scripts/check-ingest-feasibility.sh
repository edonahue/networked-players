#!/usr/bin/env bash
#
# Pre-flight safety gate for a bounded Discogs ingest slice. Two distinct
# risks are guarded separately and explicitly:
#   1. If this host has never run `uv`, the FIRST `uv run`/`uv sync` here may
#      need to download a managed Python toolchain (if the system Python
#      doesn't satisfy pyproject.toml's requires-python) plus the project's
#      pyarrow/duckdb/lxml wheels. That is real disk/network cost, not
#      "free," and is measured and guarded before we even touch the manifest.
#   2. The releases dump itself (see docs/DATA_SIZING.md for current scale)
#      is checked via a HEAD request -- no bytes downloaded -- before
#      deciding whether to proceed. parse-releases is the only implemented
#      parser (ADR 0006), so "releases" is the only object kind worth
#      checking here.
#
# Config (env vars, or sourced from git-ignored local/ingest.env, same
# pattern as scripts/run-ingest.sh):
#   SNAPSHOT       Required. YYYYMMDD, first of month (e.g. 20260601).
#   MAX_RELEASES   Optional. Cap for the parse step. Default: 2000.
#   FLOOR_MB       Optional. Minimum free MB to keep after any step. Default: 500.
#
# Usage:  SNAPSHOT=20260601 ./scripts/check-ingest-feasibility.sh
set -euo pipefail

# Do not run this with sudo: nothing here needs root, and `sudo` resets
# PATH/HOME so a uv already installed at ~/.local/bin becomes invisible.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "ABORT: do not run this script with sudo. Re-run as your normal user:" >&2
  echo "    bash scripts/check-ingest-feasibility.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Defensive: make sure ~/.local/bin (where `uv` lives) is on PATH even if
# this shell never sourced ~/.profile.
export PATH="${HOME}/.local/bin:${PATH}"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi
: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD (first of month), e.g. SNAPSHOT=20260601}"
MAX_RELEASES="${MAX_RELEASES:-2000}"
FLOOR_MB="${FLOOR_MB:-500}"
MANIFEST_DIR="${MANIFEST_DIR:-local/manifests}"

free_mb() { echo $(( $(df -Pk . | awk 'NR==2{print $4}') / 1024 )); }

# --- Step 1: uv environment bootstrap, guarded and measured ---
if ! command -v uv >/dev/null 2>&1; then
  echo "ABORT: 'uv' is not installed. Install it first (small, ~tens of MB):" >&2
  echo "    curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "    (installs to ~/.local/bin, already on your PATH via ~/.profile)" >&2
  exit 1
fi

before_mb=$(free_mb)
if (( before_mb < FLOOR_MB + 200 )); then
  echo "ABORT: ${before_mb} MB free is not enough headroom for uv's first-run" >&2
  echo "       environment sync (toolchain + pyarrow/duckdb/lxml, plausibly" >&2
  echo "       150-300MB) on top of the ${FLOOR_MB}MB floor. Defer until the" >&2
  echo "       NVMe is mounted." >&2
  exit 1
fi
echo "==> ${before_mb} MB free; syncing the uv project environment..."
uv sync 2>&1 | tail -20
after_mb=$(free_mb)
echo "==> uv environment ready. Free space ${before_mb}MB -> ${after_mb}MB (used $(( before_mb - after_mb ))MB)."
if (( after_mb < FLOOR_MB )); then
  echo "ABORT: only ${after_mb} MB free after the uv sync (floor ${FLOOR_MB}MB)." >&2
  echo "       Environment is installed for next time, but stopping before the manifest." >&2
  exit 1
fi

# --- Step 2: manifest (now cheap -- env already exists) ---
YEAR="${SNAPSHOT:0:4}"
RELEASES_FILE="discogs_${SNAPSHOT}_releases.xml.gz"
SOURCE_URL="https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data/${YEAR}/${RELEASES_FILE}"
MANIFEST_PATH="${MANIFEST_DIR}/discogs-${SNAPSHOT}.json"

mkdir -p "${MANIFEST_DIR}"
uv run networked-players-catalog manifest --snapshot "${SNAPSHOT}" --output "${MANIFEST_PATH}"

# --- Step 3: dump size via HEAD, no download ---
echo "==> HEAD ${SOURCE_URL}"
headers="$(curl -sIL --max-time 30 "${SOURCE_URL}" || true)"
content_length="$(printf '%s' "${headers}" | grep -i '^content-length:' | tail -1 | tr -d '\r' | awk '{print $2}')"

if [[ -z "${content_length}" ]]; then
  echo "==> Could not determine the object size (HEAD failed, or no"
  echo "    Content-Length -- this network sometimes gets HTTP 403 from"
  echo "    Discogs' S3; see docs/OPERATOR_SETUP.md). Treating as UNSAFE."
  echo "==> DEFERRED: no download attempted. Manifest saved at ${MANIFEST_PATH}."
  exit 0
fi

free_bytes=$(( $(free_mb) * 1024 * 1024 ))
floor_bytes=$(( FLOOR_MB * 1024 * 1024 ))
required_bytes=$(( content_length + floor_bytes ))
human() { numfmt --to=iec-i --suffix=B "$1" 2>/dev/null || echo "${1} B"; }

echo "==> Releases object size : $(human "${content_length}")"
echo "==> Free space here      : $(human "${free_bytes}")"
echo "==> Required (object + ${FLOOR_MB}MB floor): $(human "${required_bytes}")"

if (( free_bytes < required_bytes )); then
  echo "==> NOT SAFE: short by $(human $(( required_bytes - free_bytes )))."
  echo "==> DEFERRED: no download attempted, nothing partial left behind."
  echo "    Re-run after the NVMe is attached and local/ moves there."
  exit 0
fi

echo "==> SAFE: proceeding with a bounded slice (MAX_RELEASES=${MAX_RELEASES})."
SNAPSHOT="${SNAPSHOT}" MAX_RELEASES="${MAX_RELEASES}" "${REPO_ROOT}/scripts/run-ingest.sh"
