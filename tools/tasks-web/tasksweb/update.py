"""Update: bring the Work workspace to the latest release.

`tools/machine/work.py` does the work (check, fast-forward to a release tag, run update.sh); the server only runs it
as a command in the served Work root and keeps the last check in memory. A check is throttled to one per hour, an
apply never runs twice at once, and the brains are never touched. After a successful apply the server restarts itself
(see `restart_process` in tasks-web.py) so that the new code and static files are served on the same port.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import TOOLS_ROOT, TaskError, python_environment, tasks_launch
from .markdown import MARKDOWN

UPDATE_CHECK_TIMEOUT = 45
UPDATE_APPLY_TIMEOUT = 660  # update.sh may take up to 600 s
UPDATE_THROTTLE = 3600.0
UPDATE_VERSION_RE = re.compile(r"v\d+\.\d+\.\d+")
UPDATE_APPLY_LOCK = threading.Lock()


def update_command(work: Path, *args: str) -> list[str]:
    """`work.py <args>` through uv (the served Work's own copy when it has one, else this checkout's)."""
    script = work / "tools/machine/work.py"
    path = str(script if script.is_file() else TOOLS_ROOT / "tools/machine/work.py")
    uv = shutil.which("uv") or tasks_launch.find_uv()
    return [uv, "run", path, *args] if uv else [sys.executable, path, *args]


def run_update(work: Path, args: list[str], timeout: int) -> dict:
    """The JSON report of `work.py update …`; a report with state `error` when the command cannot run or answers nothing readable."""
    failure = {"state": "error", "current": None, "latest": None, "kind": None, "notes": None, "commits": [], "commits_total": 0,
               "files": 0, "reasons": [], "error": None, "fetched": False, "branch": None, "remote": None, "head": None}
    environment = python_environment()
    environment["WORK_DIR"] = str(work)
    try:
        result = subprocess.run(update_command(work, "update", *args, "--json"), cwd=work, env=environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {**failure, "error": "The update command timed out.", "reasons": ["The update command timed out."]}
    except OSError:
        return {**failure, "error": "Could not start the update command.", "reasons": ["Could not start the update command."]}
    try:
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or "state" not in report:
            raise ValueError
    except ValueError:
        message = "The update command gave no readable answer."
        return {**failure, "error": message, "reasons": [message]}
    return report


def update_notes_html(report: dict) -> str:
    notes = report.get("notes")
    return MARKDOWN.render(notes, {"id": "", "ids": set()}) if isinstance(notes, str) and notes.strip() else ""


class UpdateState:
    """The last update check of the served Work, kept in memory."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.report: dict | None = None
        self.stamp = 0.0
        self.checked_at: str | None = None

    def public(self, cached: bool = False) -> dict:
        if self.report is None:
            return {"state": None}
        return {**self.report, "notes_html": update_notes_html(self.report), "checked_at": self.checked_at, "cached": cached}

    def check(self, work: Path, force: bool, clock=time.monotonic) -> dict:
        with self.lock:
            if self.report is not None and not force and self.report["state"] != "error" and clock() - self.stamp < UPDATE_THROTTLE:
                return self.public(cached=True)
            self.report = run_update(work, ["--check"], UPDATE_CHECK_TIMEOUT)
            self.stamp = clock()
            self.checked_at = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
            return self.public()

    def forget(self) -> None:
        with self.lock:
            self.report = None


def update_apply(work: Path, version: str, state: UpdateState) -> tuple[HTTPStatus, dict]:
    """Apply the release the page showed. 409 when the update is refused or fails before any change; 200 otherwise."""
    if not UPDATE_APPLY_LOCK.acquire(blocking=False):
        raise TaskError(HTTPStatus.CONFLICT, "An update is already running.")
    try:
        report = run_update(work, ["--apply", "--to", version], UPDATE_APPLY_TIMEOUT)
        state.forget()
    finally:
        UPDATE_APPLY_LOCK.release()
    report.setdefault("applied", False)
    if report["applied"] or report["state"] == "up-to-date":
        return HTTPStatus.OK, report
    message = "; ".join(str(reason) for reason in report.get("reasons") or []) or report.get("error") or "The update was refused."
    return HTTPStatus.CONFLICT, {**report, "error": message}
