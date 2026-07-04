#!/usr/bin/env bash
#
# Replicate a catalog dataset to an x86_64 Swarm worker's local cache (ADR
# 0025). Thin wrapper over run-playbook-local.sh -- same pattern as
# run-equip-x86-workers-local.sh.
#
# Usage: ./infra/ansible/run-replicate-dataset-x86-local.sh [extra ansible-playbook args...]
#   ./infra/ansible/run-replicate-dataset-x86-local.sh \
#     -e dataset=discogs -e snapshot=20260601 -e catalog_data_url=http://<lan-ip>:8791
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" replicate-dataset-x86.yml "$@"
