#!/usr/bin/env bash
#
# Replicate the one-hop dataset to a Pi worker's bounded local cache (ADR
# 0025). Thin wrapper over run-playbook-local.sh -- same pattern as
# run-equip-workers-local.sh. Always pass --limit against a single Pi for a
# first trial run.
#
# Usage: ./infra/ansible/run-replicate-dataset-pi-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-replicate-dataset-pi-local.sh \
#     --limit worker-01 -e snapshot=20260601 -e catalog_data_url=http://<lan-ip>:8791
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" replicate-dataset-pi.yml "$@"
