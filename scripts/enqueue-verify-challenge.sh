#!/usr/bin/env bash
#
# Enqueue challenge-evidence verification shards across the joined Pi
# workers. Thin wrapper: sources local/jobs-broker.env (written by
# infra/swarm/deploy-jobs-broker.sh) to build JOBS_BROKER_URL, then runs the
# actual driver (scripts/enqueue_verify_challenge.py).
#
# Prerequisites (not checked here -- each fails loudly on its own if
# skipped):
#   - infra/swarm/deploy-jobs-broker.sh already running (jobs broker up)
#   - infra/ansible/run-deploy-verify-job-local.sh already run once (job body
#     + artifact deployed to each targeted Pi's rq-jobs directory)
#   - each targeted Pi already holds a validated one-hop cache matching the
#     artifact's snapshot (ADR 0025 -- make replicate-pi)
#
# Results are written to local/jobs/ only -- see
# docs/decisions/0018-benchmark-results-local-only.md.
#
# Usage:  ./scripts/enqueue-verify-challenge.sh
#         ./scripts/enqueue-verify-challenge.sh --shard-size 2
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

exec uv run --extra jobs python3 "${REPO_ROOT}/scripts/enqueue_verify_challenge.py" "$@"
