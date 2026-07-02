#!/usr/bin/env bash
#
# Idempotently bring up Portainer CE as a plain (non-Swarm) container. Binds
# to your Tailscale IP if tailscale is installed and connected (reachable
# from any device on your tailnet, nothing else); otherwise falls back to
# loopback-only. See docker-compose.portainer.yml and
# docs/decisions/0009-portainer-tailscale-access.md.
#
# Usage: ./infra/swarm/deploy-portainer.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

FLOOR_MB="${FLOOR_MB:-1000}"
free_mb=$(( $(df -Pk . | awk 'NR==2{print $4}') / 1024 ))
if (( free_mb < FLOOR_MB )); then
  echo "ABORT: only ${free_mb} MB free (floor: ${FLOOR_MB} MB)." >&2
  exit 1
fi
echo "==> Free space OK: ${free_mb} MB free (floor ${FLOOR_MB} MB)."

if command -v tailscale >/dev/null 2>&1 && ts_ip="$(tailscale ip -4 2>/dev/null)" && [[ -n "${ts_ip}" ]]; then
  PORTAINER_BIND_IP="${ts_ip}"
  echo "==> Tailscale connected; binding to ${PORTAINER_BIND_IP} (tailnet-only)."
else
  PORTAINER_BIND_IP="127.0.0.1"
  echo "==> Tailscale not connected; binding to loopback only."
  echo "    Run ./scripts/install-tailscale.sh first for tailnet access."
fi

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../scripts/lib/docker-compose.sh"
docker_sudo_setup

if [[ "${DC_USE_SUDO}" -eq 1 ]]; then
  sudo env "PORTAINER_BIND_IP=${PORTAINER_BIND_IP}" docker compose -f docker-compose.portainer.yml up -d
else
  PORTAINER_BIND_IP="${PORTAINER_BIND_IP}" docker compose -f docker-compose.portainer.yml up -d
fi

echo "==> Done. Reach it at: https://${PORTAINER_BIND_IP}:9443"
echo "    Set the admin password within 5 minutes of container start."
