#!/usr/bin/env bash
#
# Shared docker/docker-compose sudo-fallback and running-service helpers.
# Source this, don't execute it directly:
#   # shellcheck disable=SC1091
#   source "$(dirname "${BASH_SOURCE[0]}")/lib/docker-compose.sh"
#   docker_sudo_setup docker-compose.coordination.yml
#
# Previously duplicated verbatim across deploy-coordination.sh,
# backup-coordination-stack.sh, restore-coordination-stack.sh,
# deploy-portainer.sh, and migrate-coordination-volumes-to-nvme.sh --
# consolidated 2026-07-02 after fixing the same running-service bug twice in
# two of those copies.

# Usage: docker_sudo_setup [compose-file]
# Populates the global DOCKER array (plain `docker`, sudo-prefixed if the
# caller isn't in the docker group) and DC_USE_SUDO (0/1). If a compose file
# is given, also populates DC (`docker compose -f <file>`, same sudo rule).
docker_sudo_setup() {
  local compose_file="${1:-}"
  if ! id -nG "$(whoami)" | tr ' ' '\n' | grep -qx docker; then
    echo "==> Not in the docker group this session; using sudo."
    DOCKER=(sudo docker)
    DC_USE_SUDO=1
  else
    DOCKER=(docker)
    DC_USE_SUDO=0
  fi
  if [[ -n "${compose_file}" ]]; then
    DC=("${DOCKER[@]}" compose -f "${compose_file}")
  fi
}

# Usage: coordination_stack_running (reads the global DC array; call
# docker_sudo_setup with a compose file first). Returns 0 if postgres AND
# redis are both running.
#
# Not a plain count: docker-compose.coordination.yml and
# docker-compose.portainer.yml share an inferred project name ("swarm"), so
# `ps`/`--services` here lists every service in that project -- including
# portainer -- not just this file's own. Confirmed live 2026-07-02 (twice --
# switching from --format '{{.Name}}' to --services alone did NOT fix it,
# since --services turned out to be project-scoped too). Check by name.
coordination_stack_running() {
  local running_services
  running_services="$("${DC[@]}" ps --status running --services 2>/dev/null || true)"
  grep -qx postgres <<<"${running_services}" && grep -qx redis <<<"${running_services}"
}
