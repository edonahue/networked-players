#!/usr/bin/env bash
# Read standing worker advertisements without printing the broker credential.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/local/jobs-broker.env"

[[ -f "${ENV_FILE}" ]] || { echo "ABORT: missing ${ENV_FILE}" >&2; exit 1; }
# shellcheck disable=SC1090
source "${ENV_FILE}"
: "${JOBS_BROKER_BIND_IP:?missing from local jobs broker environment}"
: "${JOBS_BROKER_PASSWORD:?missing from local jobs broker environment}"

export JOBS_BROKER_URL="redis://:${JOBS_BROKER_PASSWORD}@${JOBS_BROKER_BIND_IP}:${JOBS_BROKER_PORT:-6380}/0"
cd "${REPO_ROOT}"
exec uv run networked-players-platform cluster-status "$@"
