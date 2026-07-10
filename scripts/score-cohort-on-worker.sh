#!/usr/bin/env bash
#
# Score a resolved cohort's connectivity ON a worker node instead of the
# coordination host, keeping the memory-heavy reach expansion (ADR 0033) off
# the Swarm manager. The worker must already hold a validated one-hop cache
# for --snapshot-date (ADR 0025 -- make replicate-x86) and be current on the
# scorer code (git pull + uv sync); this script does neither, and fails
# loudly if either is missing.
#
# Flow: copy the cohort's resolved.json up, run score-cohort-connectivity on
# the worker against its own local cache, fetch the four output artifacts
# back into the same local/analysis/cohorts/<source-id>/ directory the
# on-host command would have written. No hostnames live here -- the worker is
# resolved from the ansible inventory, and remote paths use the worker's own
# ~ so nothing host-specific is committed.
#
# Results land under local/ only (git-ignored) -- see ADR 0018.
#
# Usage:
#   ./scripts/score-cohort-on-worker.sh --source-id <id> --snapshot-date <YYYYMMDD>
#   ... [--worker zimaworker1] [--memory-limit 2GB] [--threads 3]
#   ... [--pair-timeout-seconds 180] [--max-frontier-expansion 300] [--max-reach-rows 2000000]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

INVENTORY="infra/ansible/inventories/local/hosts.yml"
WORKER="zimaworker1"
SOURCE_ID=""
SNAPSHOT_DATE=""
MEMORY_LIMIT="2GB"
THREADS="3"
PAIR_TIMEOUT="180"
MAX_FRONTIER="300"
MAX_REACH_ROWS="2000000"
# The worker's verified one-hop cache lives under this repo-relative root
# (ADR 0025 make replicate-x86 default); override if a worker caches elsewhere.
REMOTE_CACHE_ROOT="local/cache/discogs-onehop"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-id) SOURCE_ID="$2"; shift 2 ;;
    --snapshot-date) SNAPSHOT_DATE="$2"; shift 2 ;;
    --worker) WORKER="$2"; shift 2 ;;
    --memory-limit) MEMORY_LIMIT="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --pair-timeout-seconds) PAIR_TIMEOUT="$2"; shift 2 ;;
    --max-frontier-expansion) MAX_FRONTIER="$2"; shift 2 ;;
    --max-reach-rows) MAX_REACH_ROWS="$2"; shift 2 ;;
    --remote-cache-root) REMOTE_CACHE_ROOT="$2"; shift 2 ;;
    *) echo "ABORT: unknown argument $1" >&2; exit 1 ;;
  esac
done

[[ -n "${SOURCE_ID}" ]] || { echo "ABORT: --source-id required" >&2; exit 1; }
[[ -n "${SNAPSHOT_DATE}" ]] || { echo "ABORT: --snapshot-date required" >&2; exit 1; }
[[ -f "${INVENTORY}" ]] || { echo "ABORT: no local inventory at ${INVENTORY}" >&2; exit 1; }

ANALYSIS_DIR="local/analysis/cohorts/${SOURCE_ID}"
RESOLVED="${ANALYSIS_DIR}/resolved.json"
[[ -f "${RESOLVED}" ]] || { echo "ABORT: no resolved cohort at ${RESOLVED}" >&2; exit 1; }

# Everything below runs relative to the worker's own repo checkout via ~, so
# no absolute /home path is baked into this file.
REMOTE_REPO='~/networked-players'
REMOTE_ANALYSIS="${REMOTE_REPO}/${ANALYSIS_DIR}"
REMOTE_DATASET="${REMOTE_REPO}/${REMOTE_CACHE_ROOT}/snapshot=${SNAPSHOT_DATE}"
REMOTE_OUT="${REMOTE_ANALYSIS}"

run_ansible() { uv run ansible "${WORKER}" -i "${INVENTORY}" "$@"; }

echo "==> Ensuring ${WORKER} has the scorer code and dataset cache"
# ansible -m shell parses its -a string with shlex, which chokes on embedded
# newlines/braces -- every remote command here must be a single line.
READY_CMD="cd ${REMOTE_REPO} && test -f ${REMOTE_DATASET}/manifest.json && test -f ${REMOTE_DATASET}/.verified.json && export PATH=\$HOME/.local/bin:\$PATH && uv run --quiet networked-players-catalog score-cohort-connectivity --help >/dev/null"
run_ansible -m shell -a "${READY_CMD}" >/dev/null || {
  echo "ABORT: ${WORKER} not ready -- needs current code (git pull + uv sync) and a" >&2
  echo "       verified cache at ${REMOTE_CACHE_ROOT}/snapshot=${SNAPSHOT_DATE} (make replicate-x86)." >&2
  exit 1
}

echo "==> Copying ${RESOLVED} to ${WORKER}"
run_ansible -m file -a "path=${REMOTE_ANALYSIS} state=directory" >/dev/null
run_ansible -m copy -a "src=${RESOLVED} dest=${REMOTE_ANALYSIS}/resolved.json" >/dev/null

echo "==> Scoring on ${WORKER} (memory-limit=${MEMORY_LIMIT}, threads=${THREADS}, pair-timeout=${PAIR_TIMEOUT}s)"
SCORE_CMD="cd ${REMOTE_REPO} && export PATH=\$HOME/.local/bin:\$PATH && uv run --quiet networked-players-catalog score-cohort-connectivity --resolved ${REMOTE_ANALYSIS}/resolved.json --dataset ${REMOTE_DATASET} --output-dir ${REMOTE_OUT} --memory-limit ${MEMORY_LIMIT} --threads ${THREADS} --pair-timeout-seconds ${PAIR_TIMEOUT} --max-frontier-expansion ${MAX_FRONTIER} --max-reach-rows ${MAX_REACH_ROWS}"
run_ansible -m shell -a "${SCORE_CMD}"

echo "==> Fetching artifacts back to ${ANALYSIS_DIR}/"
for artifact in connectivity.json playable-pairs.json review-report.md scoring-diagnostics.json; do
  run_ansible -m fetch \
    -a "src=${REMOTE_ANALYSIS}/${artifact} dest=${ANALYSIS_DIR}/${artifact} flat=yes" >/dev/null
done

echo "==> Done. Review ${ANALYSIS_DIR}/review-report.md and scoring-diagnostics.json."
