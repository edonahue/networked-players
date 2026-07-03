#!/usr/bin/env bash
#
# Run the guarded Swarm-join playbook (ADR 0017) against the local
# inventory. Thin wrapper over run-playbook-local.sh -- same pattern as
# run-health-local.sh/run-benchmark-local.sh/run-onboard-local.sh.
#
# Requires -e confirm_swarm_join=true (the playbook aborts without it) and
# --ask-become-pass (the join itself needs root on the worker). Always run
# with --limit against exactly one worker -- see infra/swarm/README.md.
#
# Usage: ./infra/ansible/run-swarm-join-local.sh -e confirm_swarm_join=true --ask-become-pass --limit worker-01
#
# Prefer the guarded Makefile target instead of calling this directly:
#   CONFIRM=yes ARGS="--limit worker-01" make cluster-swarm-join
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" swarm-join.yml "$@"
