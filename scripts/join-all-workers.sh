#!/usr/bin/env bash
# Join every configured worker to the manager's Docker Swarm, one at a time.
# The guarded playbook prompts for the local sudo password as needed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

for worker in worker-01 worker-02 worker-03 zimaworker1; do
  printf 'Joining %s...\n' "${worker}"
  CONFIRM=yes make cluster-swarm-join \
    ARGS="--limit ${worker} --ask-become-pass"
done

printf '\nFinal manager-side Swarm membership:\n'
sudo docker node ls
