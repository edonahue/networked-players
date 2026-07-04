#!/usr/bin/env bash
#
# Copy the benchmark probe to workers as a persistent RQ job body. Thin
# wrapper over run-playbook-local.sh -- see playbooks/deploy-rq-benchmark-job.yml.
# Run run-health-local.sh first; this assumes nodes are already reachable.
#
# Usage: ./infra/ansible/run-deploy-rq-benchmark-job-local.sh [extra ansible-playbook args...]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" deploy-rq-benchmark-job.yml "$@"
