#!/bin/zsh
# Build the macOS "Actions Brain" app (no Dock change here). Kept as a shortcut: install-app.py does the work, on
# every system; options are passed on (--replace, --dry-run, --artifacts-dir DIR, --uv PATH).
set -euo pipefail

script_dir=${0:A:h}
export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
uv_bin=$(command -v uv || true)
if [[ -z "$uv_bin" ]]; then
  print -u2 'uv was not found. Install or restore uv, then run this again.'
  exit 1
fi
exec "$uv_bin" run --quiet --script "$script_dir/install-app.py" --platform macos "$@"
