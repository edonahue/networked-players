#!/usr/bin/env bash
#
# Run the CPU/memory benchmark playbook against the local inventory. Thin
# wrapper over run-playbook-local.sh (shared ensure-ansible-installed
# guard) -- see playbooks/benchmark.yml and its own docstring. Run
# run-health-local.sh first; this assumes nodes are already reachable and
# healthy.
#
# Usage: ./infra/ansible/run-benchmark-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-benchmark-local.sh --limit workers
# Usage: BENCHMARK_ITERATIONS=50000 ./infra/ansible/run-benchmark-local.sh --limit workers
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" benchmark.yml "$@"
