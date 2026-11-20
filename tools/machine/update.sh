#!/usr/bin/env bash
# Refresh the skills and report local Git state. Never commit or push.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Each phase announces itself with a `::progress <i>/<n> <label>` line that work.py update --progress reads.
STEPS=7
step() { echo "::progress $1/$STEPS $2"; }

step 1 "Checking the configuration"
uv run tools/machine/work_config.py check
uv run tools/machine/work_config.py lock
step 2 "Installing third-party skills"
./tools/machine/install-third-party.sh --missing-only

step 3 "Copying the house skills"
uv run tools/machine/sync-house-skills.py
step 4 "Linking the skills"
./tools/machine/link-skills.sh
step 5 "Checking the links"
./tools/machine/check-links.sh
step 6 "Recording the configuration"
uv run tools/machine/work_config.py stamp

step 7 "Reading the Git state"
repos=("$ROOT")
while IFS= read -r brain; do
  if [[ -n "$brain" ]]; then repos+=("$ROOT/$brain"); fi
done <<< "$(uv run tools/machine/work_config.py list-brains)"
for repo in "${repos[@]}"; do
  if [[ -d "$repo/.git" ]]; then
    echo "== ${repo##*/} =="
    git -C "$repo" status --short --branch
    if git -C "$repo" rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
      ahead="$(git -C "$repo" rev-list --count '@{upstream}..HEAD')"
      echo "Local commits not pushed: $ahead"
    fi
  fi
done
