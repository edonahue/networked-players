#!/usr/bin/env bash
#
# Download all four Discogs dump kinds (releases, artists, labels, masters) for one
# snapshot concurrently, instead of one at a time. See ADR 0014.
#
# Why: releases/artists/labels/masters are independent objects with no
# interdependency -- manifest.py already treats them that way. Running four
# `download --kind X` invocations concurrently removes the artificial sequential
# wait time from fetching them one after another. Network bandwidth may still be the
# real ceiling on a shared connection -- this removes sequential-wait overhead on top
# of that, it doesn't promise a 4x speedup.
#
# Configure via environment variables, or an optional git-ignored local/ingest.env:
#   SNAPSHOT   Required. YYYYMMDD, first of month (e.g. 20260601).
#   RAW_DIR    Optional. Default: local/raw/discogs
#
# Usage:  SNAPSHOT=20260601 ./scripts/download-all-kinds.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi
: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD (first of month), e.g. SNAPSHOT=20260601}"
RAW_DIR="${RAW_DIR:-local/raw/discogs}"
MANIFEST_DIR="${MANIFEST_DIR:-local/manifests}"
MANIFEST_PATH="${MANIFEST_DIR}/discogs-${SNAPSHOT}.json"
LOG_DIR="local/monitoring/download-${SNAPSHOT}-$(date +%s)"

mkdir -p "${MANIFEST_DIR}" "${RAW_DIR}" "${LOG_DIR}"

echo "==> Manifest for ${SNAPSHOT}"
uv run networked-players-catalog manifest --snapshot "${SNAPSHOT}" --output "${MANIFEST_PATH}"

echo "==> Downloading all four kinds concurrently (logs: ${LOG_DIR}/)"
# download_file() has no skip-if-already-downloaded logic of its own -- a re-run with
# no local check would re-fetch every kind from scratch, even ones that already
# succeeded. The destination filename only exists post-verification (download_file()
# only renames .part -> its final name after a SHA-256 match), so its presence is a
# reliable "this kind already succeeded" signal -- skip it here instead.
kinds=(releases artists labels masters)
pids=()
run_kinds=()
for kind in "${kinds[@]}"; do
  dest="${RAW_DIR}/${SNAPSHOT}/discogs_${SNAPSHOT}_${kind}.xml.gz"
  if [[ -f "${dest}" ]]; then
    echo "    skipping ${kind}: already downloaded and verified (${dest})"
    continue
  fi
  uv run networked-players-catalog download \
    --manifest "${MANIFEST_PATH}" \
    --kind "${kind}" \
    --raw-dir "${RAW_DIR}" \
    >"${LOG_DIR}/${kind}.log" 2>&1 &
  pids+=("$!")
  run_kinds+=("${kind}")
  echo "    started ${kind} (pid $!)"
done

failed=0
for i in "${!run_kinds[@]}"; do
  if wait "${pids[$i]}"; then
    echo "==> ${run_kinds[$i]}: done"
  else
    echo "==> ${run_kinds[$i]}: FAILED -- see ${LOG_DIR}/${run_kinds[$i]}.log" >&2
    failed=1
  fi
done

if [[ "${failed}" -eq 1 ]]; then
  echo "==> One or more downloads failed. Re-run this script -- kinds that already" >&2
  echo "    succeeded will be skipped, not re-fetched from scratch." >&2
  exit 1
fi

echo "==> All four kinds downloaded."
du -h "${RAW_DIR}/${SNAPSHOT}/"*
