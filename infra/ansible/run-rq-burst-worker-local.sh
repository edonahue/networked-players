#!/usr/bin/env bash
#
# Run a single burst RQ worker against one queue. Thin wrapper over
# run-playbook-local.sh -- see playbooks/run-rq-burst-worker.yml. Always pass
# --limit and -e rq_queue_name=<queue>; invoked repeatedly (once per baseline
# run, once for the distributed fan-out) by scripts/cluster_benchmark_distributed.py.
#
# Usage: ./infra/ansible/run-rq-burst-worker-local.sh --limit worker-01.example.internal -e rq_queue_name=cluster-benchmark-baseline
#        ./infra/ansible/run-rq-burst-worker-local.sh --limit workers -e rq_queue_name=cluster-benchmark-distributed
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" run-rq-burst-worker.yml "$@"
