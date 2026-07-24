#!/usr/bin/env bash
#
# Stage (or unstage) an ad hoc artifact onto Pi workers' persistent RQ jobs
# directory. Thin wrapper over run-playbook-local.sh -- see
# playbooks/stage-artifact.yml. Always pass --limit and -e
# stage_action=stage|unstage plus the other required -e vars; invoked by
# scripts/_artifact_staging.py, once per enqueue_cohort_check.py run.
#
# Usage: ./infra/ansible/run-stage-artifact-local.sh --limit worker-01 \
#          -e stage_action=stage -e local_artifact_path=/abs/path.json \
#          -e remote_filename=cohort-input-<sha256>.json -e expected_sha256=<sha256>
#        ./infra/ansible/run-stage-artifact-local.sh --limit worker-01 \
#          -e stage_action=unstage -e remote_filename=cohort-input-<sha256>.json
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/run-playbook-local.sh" stage-artifact.yml "$@"
