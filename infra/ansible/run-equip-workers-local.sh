#!/usr/bin/env bash
#
# Run the Pi 3B worker tooling playbook against the local inventory. Thin
# wrapper over run-playbook-local.sh (shared ensure-ansible-installed
# guard) -- same pattern as run-health-local.sh/run-benchmark-local.sh.
#
# Usage: ./infra/ansible/run-equip-workers-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-equip-workers-local.sh --ask-become-pass
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" equip-workers.yml "$@"
