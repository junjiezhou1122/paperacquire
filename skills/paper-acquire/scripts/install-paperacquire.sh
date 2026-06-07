#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${PAPERACQUIRE_REPO_URL:-https://github.com/junjiezhou1122/paperacquire.git}"

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "git+${REPO_URL}"
else
  python3 -m pip install --user --upgrade "git+${REPO_URL}"
fi

echo "paperacquire installed. Try: pa where"

