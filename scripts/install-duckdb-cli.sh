#!/usr/bin/env bash
#
# Standalone DuckDB CLI (single static binary, no sudo -- the official
# installer auto-symlinks into ~/.local/bin, same place uv lives). Separate
# from the `duckdb` Python package, which ships no CLI entry point.
#
# Usage: ./scripts/install-duckdb-cli.sh
set -euo pipefail

if command -v duckdb >/dev/null 2>&1; then
  echo "==> duckdb already installed ($(duckdb --version)); nothing to do."
  exit 0
fi

echo "==> Installing the DuckDB CLI (~20 MB download) via the official installer..."
curl -LsSf https://install.duckdb.org | sh

export PATH="${HOME}/.local/bin:${PATH}"
command -v duckdb >/dev/null 2>&1 || {
  echo "ABORT: install script ran but 'duckdb' is not on PATH." >&2
  exit 1
}
echo "==> Installed: $(duckdb --version)"
