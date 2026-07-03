#!/usr/bin/env bash
#
# Establish passwordless coordinator -> worker SSH for every host in the
# `workers` group of the real, git-ignored local inventory. Safe,
# non-destructive, idempotent:
#   - never overwrites an existing keypair;
#   - never disables host-key checking (first-contact prompts stay visible);
#   - never uses sshpass;
#   - aborts immediately on the first host that fails, rather than limping
#     through the rest with a partial result.
#
# Reads target hosts from `ansible-inventory` against the real local
# inventory rather than hardcoding any IP/hostname here, so this script
# stays generic and reusable unchanged for the fourth Pi later.
#
# Usage: ./infra/ansible/bootstrap-worker-ssh.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

KEY_FILE="${HOME}/.ssh/networked-players-cluster_ed25519"

if [[ ! -f inventories/local/hosts.yml ]]; then
  echo "ABORT: inventories/local/hosts.yml not found." >&2
  echo "        cp -r inventories/example inventories/local   # then edit with real values" >&2
  exit 1
fi

if [[ -f "${KEY_FILE}" ]]; then
  echo "==> Dedicated key already exists at ${KEY_FILE}; not overwriting."
else
  echo "==> Generating a dedicated ed25519 keypair for cluster control (no passphrase,"
  echo "    matches this project's other unattended-automation keys)."
  ssh-keygen -t ed25519 -f "${KEY_FILE}" -N "" -C "networked-players-cluster"
fi
chmod 600 "${KEY_FILE}"
chmod 644 "${KEY_FILE}.pub"

echo "==> Enumerating the 'workers' group from inventories/local/hosts.yml..."
mapfile -t WORKER_HOSTS < <(
  ansible-inventory -i inventories/local/hosts.yml --list \
    | python3 -c '
import json, sys
inv = json.load(sys.stdin)
hostvars = inv.get("_meta", {}).get("hostvars", {})
for name in inv.get("workers", {}).get("hosts", []):
    hv = hostvars.get(name, {})
    host = hv.get("ansible_host", name)
    user = hv.get("ansible_user", "root")
    print(f"{name} {user} {host}")
'
)

if [[ "${#WORKER_HOSTS[@]}" -eq 0 ]]; then
  echo "ABORT: no hosts found in the 'workers' group. Add them to inventories/local/hosts.yml first." >&2
  exit 1
fi

echo "==> Found ${#WORKER_HOSTS[@]} worker(s). Copying the public key to each in turn."
echo "    You will be prompted for that worker's password. First contact with a new"
echo "    host will also show its SSH host-key fingerprint -- verify it looks right"
echo "    before accepting."
echo

for entry in "${WORKER_HOSTS[@]}"; do
  read -r name user host <<<"${entry}"
  echo "== ${name} (${user}@${host}) =="
  if ! ssh-copy-id -i "${KEY_FILE}.pub" "${user}@${host}"; then
    echo "ABORT: ssh-copy-id failed for ${name} (${user}@${host}). Stopping here --" >&2
    echo "       fix this host before retrying (already-copied hosts are unaffected)." >&2
    exit 1
  fi
  echo
done

echo "==> Key copied to all ${#WORKER_HOSTS[@]} worker(s). Verifying non-interactive SSH independently..."
for entry in "${WORKER_HOSTS[@]}"; do
  read -r name user host <<<"${entry}"
  echo "== ${name} (${user}@${host}) =="
  if ! ssh -o BatchMode=yes -i "${KEY_FILE}" "${user}@${host}" 'echo "hostname: $(hostname)"; echo "arch: $(uname -m)"'; then
    echo "ABORT: non-interactive SSH verification failed for ${name} (${user}@${host})." >&2
    exit 1
  fi
done

echo
echo "==> Done. Passwordless SSH confirmed for all ${#WORKER_HOSTS[@]} worker(s)."
