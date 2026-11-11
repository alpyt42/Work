#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Claude Code SessionStart hook: print a short workspace state (stdout is added to the session context).

Prints under ~150 words: the default brain and the brains found (resolved by `work_config.py`), one line
per repository (Work, each brain) that has uncommitted paths or commits ahead of its upstream, or a single
"all clean" line, then a pointer to `brain-state.py`. Counts only: no file name, no `artifacts/` content.
Local Git only (`git status --porcelain`, `git rev-list --count @{u}..HEAD`), each call with a 2 s timeout;
no fetch, no network. The Work root is `$CLAUDE_PROJECT_DIR`, else derived from this script's location.
The hook JSON on stdin is ignored. Any error is swallowed: the hook always exits 0 and never prints a
traceback, so it cannot disturb the session.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

GIT_TIMEOUT = 2
MAX_WORDS = 150


def git(repo: Path, *args: str) -> str | None:
    """Stdout of a local git command in `repo`, or None on any failure (not a repo, no upstream, timeout, no git)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def repo_line(label: str, repo: Path) -> str | None:
    """`<label>: N uncommitted, M unpushed` for what is non-zero, else None."""
    parts: list[str] = []
    status = git(repo, "status", "--porcelain")
    if status:
        parts.append(f"{len([line for line in status.splitlines() if line.strip()])} uncommitted")
    ahead = git(repo, "rev-list", "--count", "@{u}..HEAD")
    if ahead and ahead.strip().isdigit() and int(ahead) > 0:
        parts.append(f"{int(ahead)} unpushed")
    return f"{label}: {', '.join(parts)}" if parts else None


def load_work_config(root: Path):
    path = root / "tools/machine/work_config.py"
    os.environ.setdefault("WORK_DIR", str(root))
    spec = importlib.util.spec_from_file_location("work_config", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["work_config"] = module
    spec.loader.exec_module(module)
    return module


def build(root: Path) -> str:
    lines: list[str] = []
    brains: list[Path] = []
    try:
        wc = load_work_config(root)
        brains = wc.discover_brains(root)
        try:
            default = wc.default_brain(root)
        except Exception:
            default = None
        names = ", ".join(path.name for path in brains) or "none"
        lines.append(f"Workspace: default brain {default.name if default else 'none (choose one)'}; brains found: {names}.")
    except Exception:
        lines.append("Workspace: brains could not be listed.")
    reports = [repo_line(label, path) for label, path in [("Work", root), *[(b.name, b) for b in brains]]]
    reports = [line for line in reports if line]
    lines.extend(reports or ["Git state: all clean (Work and brains, local check only)."])
    lines.append("Brains, from the Work root: `uv run tools/brain/brain-state.py map` locates a project, `brain-state.py brief <project>` gives its briefing, "
                 "`brain-state.py find <term>` searches them; AGENTS.md (\"Find the work\") gives the command for each kind of question.")
    return "\n".join(lines)


def main() -> int:
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except Exception:
        pass
    try:
        env_root = os.environ.get("CLAUDE_PROJECT_DIR")
        root = Path(env_root).resolve() if env_root else Path(__file__).resolve().parents[3]
        text = build(root)
        words = text.split()
        if len(words) > MAX_WORDS:
            text = " ".join(words[:MAX_WORDS])
        print(text)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
