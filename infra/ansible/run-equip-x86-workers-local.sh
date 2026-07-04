#!/usr/bin/env bash
#
# Run the x86_64 Swarm worker tooling playbook (ADR 0023) against the local
# inventory. Thin wrapper over run-playbook-local.sh (shared
# ensure-ansible-installed guard) -- same pattern as
# run-equip-workers-local.sh.
#
# Usage: ./infra/ansible/run-equip-x86-workers-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-equip-x86-workers-local.sh --limit x86-worker-01 --ask-become-pass
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" equip-x86-workers.yml "$@"
