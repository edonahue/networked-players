#!/usr/bin/env bash
#
# Compare a workload's aggregate throughput distributed across the joined
# Pi workers (via the jobs broker + RQ) against the same total work run on
# one worker alone. Thin wrapper: sources local/jobs-broker.env (written by
# infra/swarm/deploy-jobs-broker.sh) to build JOBS_BROKER_URL, then runs the
# actual driver (scripts/cluster_benchmark_distributed.py).
#
# Prerequisites (not checked here -- each fails loudly on its own if skipped):
#   - infra/swarm/deploy-jobs-broker.sh already running (jobs broker up)
#   - infra/ansible/run-deploy-rq-benchmark-job-local.sh already run once
#     (probe deployed to each worker's rq-jobs directory)
#   - a real infra/ansible/inventories/local/hosts.yml with joined workers
#
# Results are written to local/benchmarks/ only -- see
# docs/decisions/0018-benchmark-results-local-only.md.
#
# Usage:  ./scripts/cluster-benchmark-distributed.sh
#         ./scripts/cluster-benchmark-distributed.sh --iterations 50000
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

exec uv run --extra jobs python3 "${REPO_ROOT}/scripts/cluster_benchmark_distributed.py" "$@"
