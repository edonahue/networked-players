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

YEAR="${SNAPSHOT:0:4}"
RELEASES_FILE="discogs_${SNAPSHOT}_releases.xml.gz"
SOURCE_URL="https://discogs-data-dumps.s3.us-west-2.amazonaws.com/data/${YEAR}/${RELEASES_FILE}"
MANIFEST_PATH="${MANIFEST_DIR}/discogs-${SNAPSHOT}.json"

mkdir -p "${MANIFEST_DIR}" "${RAW_DIR}" "${PROCESSED_DIR}"

echo "==> Snapshot ${SNAPSHOT}${MAX_RELEASES:+ (max ${MAX_RELEASES} releases)}"

echo "==> 1/4 manifest"
uv run networked-players-catalog manifest \
  --snapshot "${SNAPSHOT}" \
  --output "${MANIFEST_PATH}"

echo "==> 2/4 download (releases)"
echo "    If this fails with HTTP 403, edit ${MANIFEST_PATH} to use an officially obtained URL."
uv run networked-players-catalog download \
  --manifest "${MANIFEST_PATH}" \
  --kind releases \
  --raw-dir "${RAW_DIR}"

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
