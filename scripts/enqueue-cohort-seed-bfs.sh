#!/usr/bin/env bash
#
# Enqueue cohort seed-BFS chunks across joined workers. Thin wrapper:
# sources local/jobs-broker.env (written by infra/swarm/deploy-jobs-broker.sh)
# to build JOBS_BROKER_URL, then runs the actual driver
# (scripts/enqueue_cohort_seed_bfs.py). See ADR 0032.
#
# Prerequisites (not checked here -- each fails loudly on its own if
# skipped):
#   - infra/swarm/deploy-jobs-broker.sh already running (jobs broker up)
#   - infra/ansible/run-deploy-cohort-seed-bfs-job-local.sh already run once
#     (job body deployed to each targeted worker's rq-jobs directory)
#   - each targeted worker already holds a validated one-hop cache matching
#     --snapshot-date (ADR 0025 -- make replicate-x86 / make replicate-pi)
#
# Results are written to local/jobs/ only -- see
# docs/decisions/0018-benchmark-results-local-only.md.
#
# Usage:  ./scripts/enqueue-cohort-seed-bfs.sh --resolved <path> --snapshot-date <date>
#         ./scripts/enqueue-cohort-seed-bfs.sh --resolved <path> --snapshot-date <date> --shard-size 2
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

ENV_FILE="local/jobs-broker.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ABORT: ${ENV_FILE} not found. Run ./infra/swarm/deploy-jobs-broker.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "${ENV_FILE}"
: "${JOBS_BROKER_BIND_IP:?${ENV_FILE} is missing JOBS_BROKER_BIND_IP}"
: "${JOBS_BROKER_PORT:?${ENV_FILE} is missing JOBS_BROKER_PORT}"
: "${JOBS_BROKER_PASSWORD:?${ENV_FILE} is missing JOBS_BROKER_PASSWORD}"

export JOBS_BROKER_URL="redis://:${JOBS_BROKER_PASSWORD}@${JOBS_BROKER_BIND_IP}:${JOBS_BROKER_PORT}/0"

exec uv run --extra jobs python3 "${REPO_ROOT}/scripts/enqueue_cohort_seed_bfs.py" "$@"
