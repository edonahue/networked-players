#!/usr/bin/env bash
#
# Deploy the cohort seed-BFS job body to workers. Thin wrapper over
# run-playbook-local.sh -- see playbooks/deploy-cohort-seed-bfs-job.yml.
#
# Usage: ./infra/ansible/run-deploy-cohort-seed-bfs-job-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-deploy-cohort-seed-bfs-job-local.sh --limit worker-01
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" deploy-cohort-seed-bfs-job.yml "$@"
