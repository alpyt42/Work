#!/usr/bin/env bash
# Install the enabled third-party skills of the work configuration into .agents/skills with
# `npx skills experimental_install` (from skills-lock.json, written by `work_config.py lock`).
# Does nothing when no third-party skill is enabled. Run by bootstrap.sh and update.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

third_party="$(uv run tools/machine/work_config.py list-third-party)"
[[ -n "$third_party" ]] || exit 0
command -v npx >/dev/null || { echo "Node.js (npx) is required for third-party skills" >&2; exit 1; }

status=0
npx --yes skills experimental_install || status=$?
[[ $status -eq 0 ]] && exit 0

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
