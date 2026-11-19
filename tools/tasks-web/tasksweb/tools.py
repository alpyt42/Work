"""The Tools view: the predefined commands the page may run, and running one."""

from __future__ import annotations

import os
import shutil
import subprocess
from http import HTTPStatus
from pathlib import Path

from .common import TOOLS_ROOT, TaskError, WORK, python_environment, tasks_launch

# In a tool's arguments: the folder name of the chosen brain, for a script that picks a brain by name rather than from BRAIN_DIR.
BRAIN_ARG = "<brain>"
TOOLS = {
    "links": ("Memory", "Check links", "Checks the Markdown links of the brain.", "brain/check-links.py", ()),
    "brains": ("Memory", "List brains", "Shows the memories present and the transcripts they track.", "brain/brain-state.py", ("brains",)),
    "map": ("Memory", "Brain map", "One line per project: page, register prefix, actions by state, overdue, proposed decisions, last timeline entry.", "brain/brain-state.py", ("map", "--brain", BRAIN_ARG)),
    "timeline-roll": ("Memory", "Timeline months to move", "Dry run: lists the timeline entries of past months that would move to journal/.", "brain/timeline.py", ("roll",)),
    "transcripts": ("Memory", "New transcripts", "Finds the transcripts that no brain tracks.", "brain/brain-state.py", ("transcripts", "--new")),
    "board": ("Actions", "Text view of actions", "Shows the registers by project in a terminal format.", "brain/action.py", ("board",)),
    "sweep_preview": ("Actions", "Actions to sort (preview)", "Lists the actions placed under a section that does not match their state (checked, cancelled or reopened), without changing anything.", "brain/action.py", ("sweep",)),
    "sweep_write": ("Actions", "Sort actions by status", "Moves each action into Open, Done or Cancelled according to its state (changes the registers; recoverable with Git, but outside the interface's undo stack).", "brain/action.py", ("sweep", "--write")),
    "archive_preview": ("Actions", "Actions to archive (preview)", "Lists the actions closed for more than 30 days that would move to state/actions-archive-YYYY.md, without changing anything.", "brain/action.py", ("archive",)),
    "archive_write": ("Actions", "Archive actions", "Moves the actions closed for more than 30 days to state/actions-archive-YYYY.md (changes the registers; recoverable with Git, but outside the interface's undo stack).", "brain/action.py", ("archive", "--write")),
    "repositories": ("Repositories", "Check repositories", "Compares the local clones with the private catalogue and checks their Git identity.", "repos/client-repos.py", ("check",)),
}


# Tools that write local brain files ask for a confirmation in the page before running.
TOOL_CONFIRM = {
    "sweep_write": "Sort the actions by status now? Run the preview first to see what will move.",
    "archive_write": "Archive the actions closed for more than 30 days now? Run the preview first to see what will move.",
}


BASH_MISSING = ("This tool is a shell script: on Windows it needs Bash on the PATH (Git Bash, installed with Git for Windows), "
                "and none was found.")


def tool_unavailable(script: str, windows: bool | None = None) -> str | None:
    """Why a tool cannot run on this computer, or None: a `.sh` tool needs Bash on Windows (macOS and Linux run it directly)."""
    windows = os.name == "nt" if windows is None else windows
    if script.endswith(".sh") and windows and not shutil.which("bash"):
        return BASH_MISSING
    return None


def tool_catalog() -> list[dict]:
    return [
        {"id": tool_id, "group": group, "label": label, "description": description,
         "command": ("" if script.endswith(".sh") else "uv run ") + "tools/" + " ".join((script, *args)), "confirm": TOOL_CONFIRM.get(tool_id),
         "unavailable": tool_unavailable(script)}
        for tool_id, (group, label, description, script, args) in TOOLS.items()
    ]


def run_tool(tool_id: str, brain: Path) -> dict:
    if tool_id not in TOOLS:
        raise TaskError(HTTPStatus.NOT_FOUND, "Unknown tool.")
    script, args = TOOLS[tool_id][3:]
    path = str(TOOLS_ROOT / "tools" / script)
    tail = [brain.name if arg == BRAIN_ARG else arg for arg in args]
    if script.endswith(".sh"):
        reason = tool_unavailable(script)
        if reason:
            return {"id": tool_id, "ok": False, "output": reason, "truncated": False}
        command = [shutil.which("bash") or "bash", path, *tail] if os.name == "nt" else [path, *tail]
    else:
        uv = shutil.which("uv") or tasks_launch.find_uv()
        if uv is None:
            raise TaskError(HTTPStatus.SERVICE_UNAVAILABLE, "uv was not found on this machine.")
        command = [uv, "run", path, *tail]
    environment = python_environment()
    environment["BRAIN_DIR"] = str(brain)
    try:
        result = subprocess.run(
            command, cwd=WORK, env=environment,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"id": tool_id, "ok": False, "output": "The 90-second limit was exceeded. Run the command again if needed.", "truncated": False}
    except OSError:
        raise TaskError(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not start this tool.") from None
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if not output:
        output = "Command finished with no output."
    truncated = len(output) > 60000
    return {"id": tool_id, "ok": result.returncode == 0, "output": output[:60000], "truncated": truncated}
