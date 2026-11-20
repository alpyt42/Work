#!/usr/bin/env bash
# Install the enabled third-party skills of the work configuration into .agents/skills with
# `npx skills experimental_install` (from skills-lock.json, written by `work_config.py lock`).
# Does nothing when no third-party skill is enabled. bootstrap.sh runs it without a flag (always installs).
# update.sh passes --missing-only: it installs only the skills whose SKILL.md is missing, because a full
# `npx skills experimental_install` can re-download every installed skill (and clone each source with its
# submodules), which takes minutes. New versions of installed skills are applied by running this script
# without a flag, or bootstrap.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

missing_only=0
case "${1:-}" in
  "") ;;
  --missing-only) missing_only=1 ;;
  *) echo "Usage: install-third-party.sh [--missing-only]" >&2; exit 2 ;;
esac

third_party="$(uv run tools/machine/work_config.py list-third-party)"
[[ -n "$third_party" ]] || exit 0

if [[ $missing_only -eq 1 ]]; then
  # A skill set aside in .agents/skills-disabled/ counts as installed: link-skills.sh puts it back without network.
  absent=""
  while IFS= read -r skill; do
    [[ -f ".agents/skills/$skill/SKILL.md" || -f ".agents/skills-disabled/$skill/SKILL.md" ]] || absent+="${absent:+ }$skill"
  done <<< "$third_party"
  if [[ -z "$absent" ]]; then
    echo "Third-party skills already installed: nothing to download."
    exit 0
  fi
  echo "Installing missing third-party skills: $absent"
fi

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
