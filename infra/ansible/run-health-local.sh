#!/usr/bin/env bash
#
# Run the read-only health playbook against the local inventory. Thin
# wrapper over run-playbook-local.sh (shared ensure-ansible-installed
# guard) -- kept as its own stable entry point since it's already
# referenced elsewhere (docs/OPERATOR_SETUP.md, docs/BUILD_PLAN.md).
#
# Prerequisite (one-time, real values -- never committed):
#   cp -r infra/ansible/inventories/example infra/ansible/inventories/local
#   # edit inventories/local/hosts.yml + host_vars/*.yml:
#   #   ansible_host: <real LAN IP>
#   #   ansible_connection: local   # this host runs the playbook against itself
#
# Usage: ./infra/ansible/run-health-local.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" health.yml
