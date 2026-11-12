#!/bin/zsh
# Start the local task manager on demand, then open it in the default browser.
# Kept for the apps built before install-app.py: the work is done by launch.py (macOS, Windows, Linux).
# No dialog from launch.py here: the app that runs this script shows the error itself.
set -euo pipefail

script_dir=${0:A:h}
export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
uv_bin=$(command -v uv || true)
if [[ -z "$uv_bin" ]]; then
  print -u2 'uv was not found. Install or restore uv, then start Actions again.'
  exit 1
fi
exec "$uv_bin" run --quiet --script "$script_dir/launch.py" --no-dialog "$@"
