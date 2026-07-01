#!/usr/bin/env bash
#
# Installs Tailscale (idempotent) and brings the connection up. If this
# device hasn't joined your tailnet yet, `tailscale up` prints a login URL --
# open it on any device to authorize this host.
#
# Usage: ./scripts/install-tailscale.sh
set -euo pipefail

if command -v tailscale >/dev/null 2>&1; then
  echo "==> tailscale already installed ($(tailscale version | head -1))."
else
  echo "==> Installing tailscale via the official install script..."
  curl -fsSL https://tailscale.com/install.sh | sudo sh
fi

echo "==> Bringing up the tailscale connection..."
echo "    (if this device isn't authorized yet, a login URL prints below --"
echo "     open it on any device to approve.)"
sudo tailscale up

echo "==> Connected. Tailscale IP for this host:"
tailscale ip -4
