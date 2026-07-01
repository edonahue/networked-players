#!/usr/bin/env bash
#
# Installs (idempotent -- overwrites with the current version) a general-purpose
# `run-and-ntfy` utility to ~/.local/bin/, matching the `rn` alias already set up in
# ~/.bashrc. Not Discogs-specific -- a personal host tool, so only this installer is
# versioned in the repo; the installed script itself stays out of git, same pattern
# as install-tailscale.sh/install-gh-cli.sh for the tools they install.
#
# Usage: ./scripts/install-run-and-ntfy.sh
set -euo pipefail

TARGET="${HOME}/.local/bin/run-and-ntfy"
mkdir -p "$(dirname "${TARGET}")"

cat > "${TARGET}" <<'SCRIPT'
#!/usr/bin/env bash
#
# Run a command, time it, and send an ntfy notification on completion --
# success/failure, elapsed time, and (on failure) the tail of its output.
# Reads NTFY_URL from the environment (see ~/.bashrc); silently skips
# notifying if unset, but still runs the command and preserves its exit code.
#
# Usage: run-and-ntfy <command> [args...]
#        rn <command> [args...]   (alias, see ~/.bashrc)
set -uo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: run-and-ntfy <command> [args...]" >&2
  exit 2
fi

notify() {
  local title="$1" message="$2" priority="${3:-default}" tags="${4:-}"
  if [[ -z "${NTFY_URL:-}" ]]; then
    echo "(NTFY_URL not set; skipping notification: ${title})" >&2
    return 0
  fi
  curl -fsS -H "Title: ${title}" -H "Priority: ${priority}" \
    ${tags:+-H "Tags: ${tags}"} -d "${message}" "${NTFY_URL}" >/dev/null \
    || echo "WARNING: ntfy notification failed (network issue?)" >&2
}

cmd_display="$*"
start_ts=$(date +%s)
output_file="$(mktemp)"
trap 'rm -f "${output_file}"' EXIT

"$@" > >(tee "${output_file}") 2>&1
exit_code=$?

elapsed=$(( $(date +%s) - start_ts ))
elapsed_human="$(printf '%dh%dm%ds' $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60)))"

if [[ ${exit_code} -eq 0 ]]; then
  notify "Done: ${cmd_display}" "Finished in ${elapsed_human}." "default" "white_check_mark"
else
  notify "FAILED (exit ${exit_code}): ${cmd_display}" \
    "After ${elapsed_human}.

$(tail -20 "${output_file}")" "urgent" "x"
fi

exit "${exit_code}"
SCRIPT

chmod +x "${TARGET}"
echo "==> Installed ${TARGET}"
echo "    Usage: run-and-ntfy <command> [args...]   (or: rn <command> [args...])"
if [[ -z "${NTFY_URL:-}" ]]; then
  echo "==> NTFY_URL isn't set in this shell -- open a new shell (or source ~/.bashrc)"
  echo "    to pick it up before using this."
fi
