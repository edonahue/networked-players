#!/usr/bin/env bash
# Prepare the joined Swarm for the smoke test and jobs broker.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

sudo -v
make cluster-smoke-test

sudo mkdir -p /mnt/data/networked-players/jobs-broker
sudo chown -R "${USER}:${USER}" /mnt/data/networked-players/jobs-broker

if ! grep -q '^JOBS_BROKER_DATA_DIR=' local/jobs-broker.env; then
  printf '\nJOBS_BROKER_DATA_DIR=/mnt/data/networked-players/jobs-broker\n' \
    >> local/jobs-broker.env
fi

make deploy-jobs-broker
make platform-status
sudo docker node ls
