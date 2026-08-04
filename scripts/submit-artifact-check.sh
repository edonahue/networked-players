#!/usr/bin/env bash
#
# Thin wrapper for scripts/submit_artifact_check.py: sources
# local/jobs-broker.env (written by infra/swarm/deploy-jobs-broker.sh) to
# build JOBS_BROKER_URL, then runs the actual driver via `uv run` (needed
# for the redis/rq `jobs` extra and a real Python 3.12+, not whatever
# `python3` resolves to on this host -- see
# docs/decisions/0056-unify-pi-fleet-checks-onto-capability-platform.md).
#
# Prerequisites (not checked here -- each fails loudly on its own if
# skipped): infra/swarm/deploy-jobs-broker.sh already running (jobs broker
# up), and the ADR 0034 platform runtime already deployed to every targeted
# worker (infra/ansible/run-deploy-platform-runtime-local.sh).
#
# Results are written to local/jobs/ only -- see
# docs/decisions/0018-benchmark-results-local-only.md.
#
# Usage: ./scripts/submit-artifact-check.sh --validator <name> [--limit <hostname>] [...]
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

exec uv run --extra jobs python3 "${REPO_ROOT}/scripts/submit_artifact_check.py" "$@"
