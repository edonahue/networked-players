#!/usr/bin/env bash
#
# Deploy the rounds-artifact-check job body to Pi workers. Thin wrapper over
# run-playbook-local.sh -- see playbooks/deploy-rounds-check-job.yml.
#
# Usage: ./infra/ansible/run-deploy-rounds-check-job-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-deploy-rounds-check-job-local.sh --limit worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" deploy-rounds-check-job.yml "$@"
