#!/usr/bin/env bash
#
# Manual, explicitly on-demand Dask worker for a single Pi 3B worker. Thin
# wrapper over run-playbook-local.sh -- see playbooks/run-dask-worker-burst.yml
# for the two manual gates (measured headroom, no active RQ job) this
# deliberately does not automate yet.
#
# Usage: ./infra/ansible/run-dask-worker-burst-local.sh --limit worker-01.example.internal \
#          -e dask_worker_action=start -e dask_scheduler_address=<coordination-host-lan-ip>
#        ./infra/ansible/run-dask-worker-burst-local.sh --limit worker-01.example.internal \
#          -e dask_worker_action=stop
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" run-dask-worker-burst.yml "$@"
