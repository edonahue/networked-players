#!/usr/bin/env bash
#
# Run a Discogs release-ingestion slice end to end: manifest -> download ->
# parse-releases -> validate. Operator work for a workstation or the
# coordination host; never a Raspberry Pi worker. See docs/OPERATOR_SETUP.md.
#
# Configure via environment variables, or an optional git-ignored
# local/ingest.env (sourced if present):
#
#   SNAPSHOT       Required. Monthly snapshot, YYYYMMDD, first of month (e.g. 20260501).
#   MAX_RELEASES   Optional. Cap releases parsed (omit for a full pass).
#   RAW_DIR        Optional. Default: local/raw/discogs
#   PROCESSED_DIR  Optional. Default: local/processed/discogs
#   MANIFEST_DIR   Optional. Default: local/manifests
#
# Example:  SNAPSHOT=20260501 MAX_RELEASES=10000 ./scripts/run-ingest.sh

set -euo pipefail

# Resolve repo root so the script works from any directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Optional local overrides (git-ignored).
if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi

: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD (first of month), e.g. SNAPSHOT=20260501}"
MANIFEST_DIR="${MANIFEST_DIR:-local/manifests}"
RAW_DIR="${RAW_DIR:-local/raw/discogs}"
PROCESSED_DIR="${PROCESSED_DIR:-local/processed/discogs}"

RELEASES_FILE="discogs_${SNAPSHOT}_releases.xml.gz"
MANIFEST_PATH="${MANIFEST_DIR}/discogs-${SNAPSHOT}.json"

mkdir -p "${MANIFEST_DIR}" "${RAW_DIR}" "${PROCESSED_DIR}"

echo "==> Snapshot ${SNAPSHOT}${MAX_RELEASES:+ (max ${MAX_RELEASES} releases)}"

echo "==> 1/4 manifest"
uv run networked-players-catalog manifest \
  --snapshot "${SNAPSHOT}" \
  --output "${MANIFEST_PATH}"

# The manifest (built by manifest.py's object_url()) is the single source of truth
# for the real download URL -- read it back for provenance rather than
# reconstructing it here a second time, so recorded provenance always matches
# whatever was actually fetched, even if the URL scheme changes again later.
SOURCE_URL="$(uv run python3 -c "
import json
with open('${MANIFEST_PATH}') as f:
    manifest = json.load(f)
print(next(o['url'] for o in manifest['objects'] if o['kind'] == 'releases'))
")"

echo "==> 2/4 download (releases)"
# download_file() has no skip-if-already-downloaded logic of its own -- without this
# check, every run would re-fetch the full compressed dump even when an already
# checksum-verified copy exists locally (confirmed live: this cost a needless ~11GB
# re-download during a bounded-slice profiling run that only needed the file already
# on disk). The destination filename only exists post-verification (download_file()
# only renames .part -> its final name after a SHA-256 match), so its presence is a
# reliable "already downloaded and verified" signal.
RELEASES_DEST="${RAW_DIR}/${SNAPSHOT}/${RELEASES_FILE}"
if [[ -f "${RELEASES_DEST}" ]]; then
  echo "    already downloaded and verified: ${RELEASES_DEST}"
else
  echo "    If this fails, edit ${MANIFEST_PATH}'s url/source_url to a working link."
  uv run networked-players-catalog download \
    --manifest "${MANIFEST_PATH}" \
    --kind releases \
    --raw-dir "${RAW_DIR}"
fi

echo "==> 3/4 parse-releases"
parse_args=(
  --input "${RAW_DIR}/${SNAPSHOT}/${RELEASES_FILE}"
  --snapshot "${SNAPSHOT}"
  --source-url "${SOURCE_URL}"
  --output-root "${PROCESSED_DIR}"
)
if [[ -n "${MAX_RELEASES:-}" ]]; then
  parse_args+=(--max-releases "${MAX_RELEASES}")
fi
uv run networked-players-catalog parse-releases "${parse_args[@]}"

echo "==> 4/4 validate"
uv run networked-players-catalog validate \
  --dataset "${PROCESSED_DIR}/snapshot=${SNAPSHOT}"

echo "==> Done. Measure with:"
echo "    du -h -d 3 ${PROCESSED_DIR}/snapshot=${SNAPSHOT}"
