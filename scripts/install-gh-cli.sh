#!/usr/bin/env bash
#
# Installs the GitHub CLI (gh) as a standalone binary in ~/.local/bin -- no
# sudo, no apt (this host's apt sources have had unrelated GPG issues, so
# this deliberately avoids adding another apt repo for one binary).
#
# After this, authenticate once and wire it into git's credential helper:
#   gh auth login
#   gh auth setup-git
#
# Usage: ./scripts/install-gh-cli.sh
set -euo pipefail

if command -v gh >/dev/null 2>&1; then
  echo "==> gh already installed ($(gh --version | head -1)); nothing to do."
  exit 0
fi

echo "==> Looking up the latest gh release..."
tag="$(curl -s --max-time 15 https://api.github.com/repos/cli/cli/releases/latest \
  | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')"
[[ -n "${tag}" ]] || { echo "ABORT: could not determine the latest gh release tag." >&2; exit 1; }
version="${tag#v}"
url="https://github.com/cli/cli/releases/download/${tag}/gh_${version}_linux_amd64.tar.gz"

echo "==> Downloading ${tag}..."
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT
curl -LsSf "${url}" -o "${tmp_dir}/gh.tar.gz"
tar -xzf "${tmp_dir}/gh.tar.gz" -C "${tmp_dir}"

mkdir -p "${HOME}/.local/bin"
install -m 755 "${tmp_dir}/gh_${version}_linux_amd64/bin/gh" "${HOME}/.local/bin/gh"

export PATH="${HOME}/.local/bin:${PATH}"
command -v gh >/dev/null 2>&1 || { echo "ABORT: gh not on PATH after install." >&2; exit 1; }
echo "==> Installed: $(gh --version | head -1)"
echo
echo "==> Next, authenticate (interactive) and wire it into git:"
echo "    gh auth login"
echo "    gh auth setup-git"
