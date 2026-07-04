#!/usr/bin/env bash
#
# Check for a partially-completed (interrupted or still-running) Discogs
# ingest and report exactly how much real, VALID output survives -- see
# scripts/check_ingest_recovery.py's own docstring for why "valid" needs
# checking at all (a hard kill can leave the last part truncated) rather
# than just counting files.
#
# Config (env vars, or sourced from git-ignored local/ingest.env, same
# pattern as scripts/run-ingest.sh / scripts/profile-discogs-dataset.sh):
#   SNAPSHOT        Required. YYYYMMDD, e.g. 20260601.
#   PROCESSED_DIR   Optional. Default: local/processed/discogs
#   CHUNK_RELEASES  Optional. Default: 5000 (parse-releases' own default --
#                   override if you ran with a different --chunk-releases).
#
# Usage:  SNAPSHOT=20260601 ./scripts/check-ingest-recovery.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi

: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD, e.g. SNAPSHOT=20260601}"
PROCESSED_DIR="${PROCESSED_DIR:-local/processed/discogs}"
CHUNK_RELEASES="${CHUNK_RELEASES:-5000}"

if ! command -v duckdb >/dev/null 2>&1; then
  echo "ABORT: duckdb CLI not found on PATH. Install it with:" >&2
  echo "    ./scripts/install-duckdb-cli.sh" >&2
  exit 1
fi

exec uv run python3 "${REPO_ROOT}/scripts/check_ingest_recovery.py" \
  "${SNAPSHOT}" --processed-dir "${PROCESSED_DIR}" --chunk-releases "${CHUNK_RELEASES}"
