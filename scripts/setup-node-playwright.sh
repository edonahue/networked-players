#!/usr/bin/env bash
#
# Selects Node 22 via nvm, installs apps/web's deps, installs Playwright's
# chromium binary + Debian system libs (--with-deps shells out to apt-get
# itself and will prompt for sudo -- expected, one-time per Debian release).
#
# Usage: ./scripts/setup-node-playwright.sh
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "ABORT: do not run with sudo; nvm/npm must run as your normal user." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[[ -s "${NVM_DIR}/nvm.sh" ]] || { echo "ABORT: nvm not found at ${NVM_DIR}/nvm.sh." >&2; exit 1; }
# shellcheck disable=SC1091
source "${NVM_DIR}/nvm.sh"

echo "==> Installing/selecting Node 22 via nvm..."
nvm install 22
nvm alias default 22
nvm use default
node --version | grep -q '^v22\.' || { echo "ABORT: expected Node 22.x, got $(node --version)" >&2; exit 1; }
echo "==> node --version: $(node --version)"
echo "==> which node:     $(which node)"

cd "${REPO_ROOT}/apps/web"
echo "==> npm ci in apps/web..."
npm ci

echo "==> Installing Playwright's Chromium + Debian system libs (may prompt sudo)..."
npx playwright install --with-deps chromium

echo "==> Done. Verify with: cd apps/web && npm run test:smoke"
