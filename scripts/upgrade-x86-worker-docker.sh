#!/usr/bin/env bash
# Upgrade the dedicated x86 Swarm worker's Docker Engine and verify membership.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INVENTORY="${REPO_ROOT}/infra/ansible/inventories/local/hosts.yml"

cd "${REPO_ROOT}"

uv run ansible zimaworker1 -i "${INVENTORY}" -b -K -m apt \
  -a "name=docker-ce=5:29.6.1-1~debian.11~bullseye,docker-ce-cli=5:29.6.1-1~debian.11~bullseye state=present update_cache=yes"

uv run ansible zimaworker1 -i "${INVENTORY}" -b -K -m systemd \
  -a "name=docker state=restarted enabled=yes"

printf '\nWorker Docker version:\n'
uv run ansible zimaworker1 -i "${INVENTORY}" -m command -a "docker --version"

printf '\nManager Swarm membership:\n'
sudo docker node ls
