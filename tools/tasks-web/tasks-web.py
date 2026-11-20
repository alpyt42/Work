#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "markdown-it-py==3.0.0",
#   "tzdata>=2024.1; sys_platform == 'win32'",  # zoneinfo has no time zone database of its own on Windows
# ]
# ///
"""Serve a private, local action manager (Today, list and board views, docs, search, tools, Sync) backed by brain action registers.

Run from Work with: uv run tools/tasks-web/tasks-web.py
Only listens on 127.0.0.1. The Markdown registers remain the source of truth.

A Work can hold several brains (`brain`, `brain-<name>`): the page switches between them without a
restart, and every /api route takes an optional `brain=<name>` (a discovered name, never a path).
`--brain` only chooses the default brain (otherwise the default brain of Work, see tools/machine/work_config.py).
WORK_DIR points to another Work root; a relative `--brain` is read from that root, and a folder that is not a brain is refused.

This file is the entry point (the arguments, `main()`, the restart after an update); the code is in the package tasksweb/ beside it.
"""

from __future__ import annotations

import argparse
import os
import shutil  # noqa: F401
import subprocess  # noqa: F401
import sys
from pathlib import Path

# The code is in the package tasksweb/ beside this file (REFERENCE.md, section "Code layout"): importable whether this file runs as a
# script or is loaded by path, as tests/test_tasks_web.py does.
_APP_DIR = str(Path(__file__).resolve().parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from tasksweb.brains import brain_option, default_brain_dir  # noqa: E402
from tasksweb.common import WORK, tasks_launch, work_config  # noqa: E402
from tasksweb.server import TaskServer  # noqa: E402
from tasksweb.store import Store  # noqa: E402

# Re-exported for tests/test_tasks_web.py, which reaches them as `tasks_web.<name>` (with `os`, `shutil` and `subprocess` above).
from tasksweb.brains import brain_label, client_display_name, discover_brains  # noqa: E402, F401
from tasksweb.common import NOTE_BACKLINK_LIMIT, TOOLS_ROOT, doc_date, doc_type  # noqa: E402, F401
from tasksweb.docs import DOC_SIZE_LIMIT, DocEntry  # noqa: E402, F401
from tasksweb.git_sync import (  # noqa: E402, F401
    GIT_ADD_TIMEOUT, GIT_BODY_LIMIT, GIT_CHANGE_LIMIT, GIT_COMMIT_TIMEOUT, GIT_COMPARE_LIMIT, GIT_COMPARE_LINES, GIT_LOCK, GIT_PUSH_TIMEOUT,
    GIT_READ_TIMEOUT, GIT_STALE, git_commit_message, git_commit_reason, git_online_copy, git_program, git_project, git_push_reason,
    git_web_url, run_git_write, to_lines,
)
from tasksweb.markdown import MARKDOWN, fold, fold_mapped, split_front_matter  # noqa: E402, F401
from tasksweb.settings import settings_config_module  # noqa: E402, F401
from tasksweb.tools import BASH_MISSING, BRAIN_ARG, TOOLS, run_tool, tool_catalog, tool_unavailable  # noqa: E402, F401
from tasksweb.update import UPDATE_APPLY_LOCK, UpdateState, run_update, update_notes_html  # noqa: E402, F401


def restart_command() -> list[str]:
    """This same command line, run again: through uv when it is found, else with the interpreter that runs this script."""
    uv = tasks_launch.find_uv()
    script = str(Path(__file__).resolve())
    return [uv, "run", script, *sys.argv[1:]] if uv else [sys.executable, *sys.argv]


def restart_process() -> None:
    """Replace this process by a new one on the same command line (never returns). Tests replace it."""
    command = restart_command()
    os.execv(command[0], command)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brain", type=Path, default=None,
                        help="default brain (default: the default brain of Work); a relative path is read from the Work root (WORK_DIR, "
                             "else this checkout), not from the current directory; the other brains of Work are chosen in the page")
    parser.add_argument("--port", type=int, default=8765, help="local port (default: 8765)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    try:
        brain = brain_option(args.brain, WORK) if args.brain else default_brain_dir()
    except work_config.ConfigError as error:
        parser.error(f"work config error: {error}")
    except ValueError as error:
        parser.error(str(error))
    try:
        store = Store(brain)
    except ValueError as error:
        parser.error(f"{error}" + ("" if args.brain else " (no default brain: set \"defaultBrain\" in work-config.local.json, or pass --brain)"))
    with TaskServer(("127.0.0.1", args.port), store) as server:
        print(f"Actions: http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)", flush=True)
        print(f"Default brain: {store.brain} (Work root: {server.work})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        restart = getattr(server, "restart_requested", False)
    if restart:  # the server is closed, so the port is free for the new process
        print("Restarting after an update…", flush=True)
        restart_process()


if __name__ == "__main__":
    work_config.utf8_stdio()  # UTF-8 even into a log file on Windows
    main()
