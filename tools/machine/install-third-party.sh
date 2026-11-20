#!/usr/bin/env bash
# Install the enabled third-party skills of the work configuration into .agents/skills with
# `npx skills experimental_install` (from skills-lock.json, written by `work_config.py lock`).
# Does nothing when no third-party skill is enabled. Run by bootstrap.sh (always installs) and update.sh.
# With --if-changed, skips npx when skills-lock.json is the one recorded after the last successful install and
# every enabled third-party skill is installed. The recorded hash lives in .agents/third-party-lock.hash
# (ignored, outside .agents/skills/, so no skill listing or check sees it).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if_changed=0
case "${1:-}" in
  "") ;;
  --if-changed) if_changed=1 ;;
  *) echo "Usage: install-third-party.sh [--if-changed]" >&2; exit 2 ;;
esac

third_party="$(uv run tools/machine/work_config.py list-third-party)"
[[ -n "$third_party" ]] || exit 0

HASH_FILE=".agents/third-party-lock.hash"
lock_hash=""
[[ -f skills-lock.json ]] && lock_hash="$(git hash-object --no-filters skills-lock.json 2>/dev/null || true)"

all_installed() {
  while IFS= read -r skill; do
    [[ -f ".agents/skills/$skill/SKILL.md" ]] || return 1
  done <<< "$third_party"
}

record_hash() {
  if [[ -n "$lock_hash" ]]; then
    mkdir -p .agents
    printf '%s\n' "$lock_hash" > "$HASH_FILE"
  fi
}

if [[ $if_changed -eq 1 && -n "$lock_hash" && -f "$HASH_FILE" && "$(cat "$HASH_FILE")" == "$lock_hash" ]] && all_installed; then
  echo "Third-party skills unchanged: install skipped."
  exit 0
fi

command -v npx >/dev/null || { echo "Node.js (npx) is required for third-party skills" >&2; exit 1; }

status=0
npx --yes skills experimental_install || status=$?
if [[ $status -eq 0 ]]; then record_hash; exit 0; fi

# On Windows the installer can fail after installing every skill, while it removes the copy it made for
# another agent ("OpenCode: ENOENT ... unlink ...SKILL.md"). Accept that there only when every enabled
# third-party skill has its SKILL.md; any other failure, or any other system, stops here.
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) ;;
  *) exit "$status" ;;
esac
missing=""
while IFS= read -r skill; do
  [[ -f ".agents/skills/$skill/SKILL.md" ]] || missing+=" $skill"
done <<< "$third_party"
if [[ -n "$missing" ]]; then
  echo "npx skills failed (exit $status) and left skills uninstalled:$missing" >&2
  exit "$status"
fi
echo "Warning: npx skills exited with status $status, but every enabled third-party skill is installed: continuing." >&2
record_hash
