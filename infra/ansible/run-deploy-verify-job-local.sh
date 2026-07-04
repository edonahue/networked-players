#!/usr/bin/env bash
#
# Deploy the challenge-evidence verification job (job body + artifact) to Pi
# workers. Thin wrapper over run-playbook-local.sh -- see
# playbooks/deploy-verify-job.yml.
#
# Usage: ./infra/ansible/run-deploy-verify-job-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-deploy-verify-job-local.sh --limit worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" deploy-verify-job.yml "$@"
