#!/usr/bin/env bash
#
# Confirm Docker is installed and the connecting user's docker-group
# membership has actually taken effect on every worker -- group changes
# from onboard.yml only apply on a fresh login, so this forces a brand-new
# SSH connection per host (ignoring any cached ControlPersist socket)
# rather than trusting a connection left open from onboarding.
#
# Usage: ./infra/ansible/verify-worker-docker.sh [--limit <group-or-host>]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

TARGET="workers"
if [[ "${1:-}" == "--limit" ]]; then
  TARGET="${2:?--limit needs a value}"
fi

if [[ ! -f inventories/local/hosts.yml ]]; then
  echo "ABORT: inventories/local/hosts.yml not found." >&2
  exit 1
fi

echo "==> Clearing any cached SSH control sockets (forces a fresh connection/login,"
echo "    which is what a docker-group change actually needs to take effect)..."
rm -f "${HOME}"/.ansible/cp/* 2>/dev/null || true

echo "==> Checking Docker + docker-group membership on '${TARGET}'..."
# No {{ }} Go-template format strings here -- Ansible's ad-hoc -a string is
# itself Jinja2-templated first, which collides with Docker's own Go
# template syntax. Plain docker info output, filtered, avoids that entirely.
ansible -i inventories/local/hosts.yml "${TARGET}" \
  -m shell \
  -a "id && docker info 2>&1 | grep -E 'Server Version|Architecture|permission denied'"
