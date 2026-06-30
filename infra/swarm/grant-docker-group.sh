#!/usr/bin/env bash
#
# Idempotently add a user to the local `docker` group so future sessions can
# run docker without sudo. NOT required for tonight's bootstrap --
# init-swarm-manager.sh uses `sudo docker` directly and works regardless of
# group membership. This is a convenience step that takes effect on next login.
#
# Usage: ./infra/swarm/grant-docker-group.sh [user]   (default: current user)
set -euo pipefail

TARGET_USER="${1:-$(whoami)}"

if ! getent group docker >/dev/null; then
  echo "No 'docker' group found -- is Docker Engine installed?" >&2
  exit 1
fi

if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
  echo "==> ${TARGET_USER} is already in the docker group; nothing to do."
else
  echo "==> Adding ${TARGET_USER} to the docker group (requires sudo password)."
  sudo usermod -aG docker "$TARGET_USER"
  echo "==> Added. Takes effect on your NEXT login (or run: newgrp docker)."
  echo "    Tonight's bootstrap does not depend on this -- it uses sudo."
fi
