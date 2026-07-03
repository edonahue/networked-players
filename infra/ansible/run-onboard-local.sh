#!/usr/bin/env bash
#
# Run the onboarding playbook (Docker install + docker-group + join-command
# report, ADR 0015) against the local inventory. Thin wrapper over
# run-playbook-local.sh (shared ensure-ansible-installed guard) -- same
# pattern as run-health-local.sh/run-benchmark-local.sh.
#
# Usage: ./infra/ansible/run-onboard-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-onboard-local.sh --limit workers --ask-become-pass
#   ./infra/ansible/run-onboard-local.sh --limit optional_build_nodes
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" onboard.yml "$@"
