#!/usr/bin/env bash
#
# Guarded, idempotent: ensure ansible-core is available (uv tool install,
# falling back to apt only if uv is unavailable), then run the read-only
# health playbook against the local inventory.
#
# Prerequisite (one-time, tonight, real values -- never committed):
#   cp -r infra/ansible/inventories/example infra/ansible/inventories/local
#   # edit inventories/local/hosts.yml + host_vars/*.yml:
#   #   ansible_host: <real LAN IP>
#   #   ansible_connection: local   # this host runs the playbook against itself
#
# Usage: ./infra/ansible/run-health-local.sh
set -euo pipefail

# Do not run this with sudo: it needs no root privileges of its own (uv tool
# install and ansible-playbook both run as your normal user), and `sudo`
# resets PATH/HOME so a uv already installed at ~/.local/bin is invisible to
# root, silently pushing this onto the apt fallback path instead.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "ABORT: do not run this script with sudo. Re-run as your normal user:" >&2
  echo "    bash infra/ansible/run-health-local.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Defensive: make sure ~/.local/bin (where `uv` and uv-installed tools live)
# is on PATH even if this shell never sourced ~/.profile.
export PATH="${HOME}/.local/bin:${PATH}"

FLOOR_MB="${FLOOR_MB:-400}"
free_mb=$(( $(df -Pk . | awk 'NR==2{print $4}') / 1024 ))
if (( free_mb < FLOOR_MB )); then
  echo "ABORT: only ${free_mb} MB free (floor: ${FLOOR_MB} MB). Not installing/running ansible." >&2
  exit 1
fi

if ! command -v ansible-playbook >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    echo "==> Installing ansible-core via 'uv tool install' (isolated, ~tens of MB)."
    uv tool install ansible-core
    export PATH="${HOME}/.local/bin:${PATH}"
  else
    echo "==> uv not found; falling back to apt (larger footprint, ~250MB installed)."
    echo "    This uses the Debian-stable 'ansible' package, NOT 'ansible-core' from"
    echo "    testing, to avoid mixing release tracks on this host."
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends ansible
  fi
fi
command -v ansible-playbook >/dev/null 2>&1 || { echo "ABORT: ansible-playbook still not on PATH." >&2; exit 1; }

if [[ ! -f inventories/local/hosts.yml ]]; then
  echo "ABORT: inventories/local/hosts.yml not found." >&2
  echo "        cp -r inventories/example inventories/local   # then edit with real values" >&2
  exit 1
fi

echo "==> Running health.yml against inventories/local/hosts.yml ..."
ansible-playbook -i inventories/local/hosts.yml playbooks/health.yml
