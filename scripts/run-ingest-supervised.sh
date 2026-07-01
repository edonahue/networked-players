#!/usr/bin/env bash
#
# Run scripts/run-ingest.sh as a supervised systemd transient unit instead of a bare
# background shell process. See ADR 0014.
#
# Why: a bare `&`-backgrounded process is tied to the shell/tool session that started
# it and gives no resource accounting or durable logging on its own. A systemd
# transient unit survives SSH/session disconnects robustly, gets real cgroup resource
# limits (Nice, I/O scheduling class, a memory ceiling), and -- once
# infra/ansible/playbooks/harden.yml's persistent journald change is applied --
# durable logging via `journalctl -u <unit>` independent of any scratch file.
#
# Requires sudo (a system-level transient unit is more robust than a --user unit,
# which needs `loginctl enable-linger` to survive logout). The workload itself runs
# as your normal user, not root -- only the unit *creation* needs root.
#
# Configure via the same environment variables as run-ingest.sh (SNAPSHOT required;
# MAX_RELEASES, RAW_DIR, PROCESSED_DIR, MANIFEST_DIR optional), or an optional
# git-ignored local/ingest.env.
#
# Usage:  SNAPSHOT=20260601 ./scripts/run-ingest-supervised.sh
#         SNAPSHOT=20260601 MAX_RELEASES=50000 ./scripts/run-ingest-supervised.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -f local/ingest.env ]]; then
  # shellcheck disable=SC1091
  source local/ingest.env
fi
: "${SNAPSHOT:?Set SNAPSHOT=YYYYMMDD (first of month), e.g. SNAPSHOT=20260601}"

UNIT_NAME="discogs-ingest-${SNAPSHOT}-$(date +%s)"

echo "==> Starting supervised unit: ${UNIT_NAME}"
echo "    Nice=10, best-effort I/O scheduling, MemoryMax=4G (observed real usage is"
echo "    ~168MB -- this is a generous safety ceiling, not a tight constraint)."

# --collect: garbage-collect the unit automatically once it exits, rather than
# leaving a stopped-but-not-cleaned-up transient unit behind on every run.
sudo systemd-run \
  --unit="${UNIT_NAME}" \
  --description="Discogs ingest ${SNAPSHOT}${MAX_RELEASES:+ (max ${MAX_RELEASES})}" \
  --collect \
  --property="Nice=10" \
  --property="IOSchedulingClass=best-effort" \
  --property="IOSchedulingPriority=7" \
  --property="MemoryMax=4G" \
  --working-directory="${REPO_ROOT}" \
  --uid="$(id -u)" \
  --gid="$(id -g)" \
  env \
    "HOME=${HOME}" \
    "PATH=${HOME}/.local/bin:${PATH}" \
    "SNAPSHOT=${SNAPSHOT}" \
    "MAX_RELEASES=${MAX_RELEASES:-}" \
    "RAW_DIR=${RAW_DIR:-}" \
    "PROCESSED_DIR=${PROCESSED_DIR:-}" \
    "MANIFEST_DIR=${MANIFEST_DIR:-}" \
    "${REPO_ROOT}/scripts/run-ingest.sh"

echo "==> Started as systemd unit: ${UNIT_NAME}"
echo "    Follow live:  journalctl -u ${UNIT_NAME} -f"
echo "    Status:       systemctl status ${UNIT_NAME}"
echo "    Stop early:   sudo systemctl stop ${UNIT_NAME}"
echo "    Resource use: systemctl status ${UNIT_NAME} (shows Memory/CPU/Tasks)"
echo "==> Consider also running: ./scripts/monitor-heavy-job.sh ${UNIT_NAME}"
