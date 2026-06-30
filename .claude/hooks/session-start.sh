#!/bin/bash
# SessionStart hook for Claude Code on the web: install Python dependencies so
# tests and linters work immediately. No-op outside remote sessions. Idempotent.
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Ensure uv (Python toolchain + dependency manager) is available.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Install dependencies with dev extras. uv installs a managed Python if needed
# and reuses the cached environment on subsequent runs.
uv sync --extra dev

# Keep uv's install location on PATH for the rest of the session.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi
