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
UPDATE_FRESH_FETCH = 600.0  # a fetch this recent makes the apply skip its own
UPDATE_VERSION_RE = re.compile(r"v\d+\.\d+\.\d+")
UPDATE_APPLY_LOCK = threading.Lock()


def update_command(work: Path, *args: str) -> list[str]:
    """`work.py <args>` through uv (the served Work's own copy when it has one, else this checkout's)."""
    script = work / "tools/machine/work.py"
    path = str(script if script.is_file() else TOOLS_ROOT / "tools/machine/work.py")
    uv = shutil.which("uv") or tasks_launch.find_uv()
    return [uv, "run", path, *args] if uv else [sys.executable, path, *args]


def _failure_report(message: str | None = None) -> dict:
    return {"state": "error", "current": None, "latest": None, "kind": None, "notes": None, "commits": [], "commits_total": 0,
            "files": 0, "reasons": [message] if message else [], "error": message, "fetched": False, "branch": None, "remote": None,
            "head": None}


def _parse_report(text: str) -> dict:
    try:
        report = json.loads(text)
        if not isinstance(report, dict) or "state" not in report:
            raise ValueError
    except ValueError:
        return _failure_report("The update command gave no readable answer.")
    return report


def _progress_event(line: str) -> dict | None:
    """The phase event of one stderr line of `work.py update --progress`, or None for any other line."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or not isinstance(event.get("label"), str):
        return None
    index, total = event.get("index"), event.get("total")
    return {"label": event["label"], "index": index if isinstance(index, int) else None, "total": total if isinstance(total, int) else None}


def run_update(work: Path, args: list[str], timeout: int, on_progress=None) -> dict:
    """The JSON report of `work.py update …`; a report with state `error` when the command cannot run or answers nothing readable.

    With `on_progress`, the command runs with `--progress` and the callback gets each phase event as it starts."""
    environment = python_environment()
    environment["WORK_DIR"] = str(work)
    command = update_command(work, "update", *args, *(["--progress"] if on_progress else []), "--json")
    if on_progress is None:
        try:
            result = subprocess.run(command, cwd=work, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return _failure_report("The update command timed out.")
        except OSError:
            return _failure_report("Could not start the update command.")
        return _parse_report(result.stdout)
    try:
        process = subprocess.Popen(command, cwd=work, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
    except OSError:
        return _failure_report("Could not start the update command.")
    chunks: list[str] = []
    other: list[str] = []

    def read_stdout() -> None:
        chunks.append(process.stdout.read())

    def read_stderr() -> None:
        for raw in process.stderr:
            event = _progress_event(raw)
            if event:
                on_progress(event)
            elif raw.strip():
                other.append(raw.rstrip())

    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return _failure_report("The update command timed out.")
    for reader in readers:
        reader.join(5)
    return _parse_report("".join(chunks))


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
        self.fetched_stamp: float | None = None  # when the last successful check fetched the tags
        self.progress_lock = threading.Lock()
        self.progress: dict | None = None  # the running apply: label, index, total, started, step_started

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
            if self.report.get("fetched") and self.report["state"] != "error":
                self.fetched_stamp = self.stamp
            self.checked_at = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
            return self.public()

    def forget(self) -> None:
        with self.lock:
            self.report = None

    def fetched_recently(self, clock=time.monotonic) -> bool:
        with self.lock:
            return self.fetched_stamp is not None and clock() - self.fetched_stamp < UPDATE_FRESH_FETCH

    def progress_begin(self, clock=time.monotonic) -> None:
        with self.progress_lock:
            now = clock()
            self.progress = {"label": None, "index": None, "total": None, "started": now, "step_started": now}

    def progress_event(self, event: dict, clock=time.monotonic) -> None:
        with self.progress_lock:
            if self.progress is not None:
                self.progress.update(label=event["label"], index=event["index"], total=event["total"], step_started=clock())

    def progress_end(self) -> None:
        with self.progress_lock:
            self.progress = None

    def progress_public(self, clock=time.monotonic) -> dict:
        with self.progress_lock:
            if self.progress is None:
                return {"running": False, "label": None, "index": None, "total": None, "elapsed": 0, "step_elapsed": 0}
            now, p = clock(), self.progress
            return {"running": True, "label": p["label"], "index": p["index"], "total": p["total"],
                    "elapsed": round(now - p["started"], 1), "step_elapsed": round(now - p["step_started"], 1)}


def update_apply(work: Path, version: str, state: UpdateState) -> tuple[HTTPStatus, dict]:
    """Apply the release the page showed. 409 when the update is refused or fails before any change; 200 otherwise."""
    if not UPDATE_APPLY_LOCK.acquire(blocking=False):
        raise TaskError(HTTPStatus.CONFLICT, "An update is already running.")
    try:
        args = ["--apply", "--to", version] + (["--no-fetch"] if state.fetched_recently() else [])
        state.progress_begin()
        report = run_update(work, args, UPDATE_APPLY_TIMEOUT, on_progress=state.progress_event)
        state.forget()
    finally:
        state.progress_end()
        UPDATE_APPLY_LOCK.release()
    report.setdefault("applied", False)
    if report["applied"] or report["state"] == "up-to-date":
        return HTTPStatus.OK, report
    message = "; ".join(str(reason) for reason in report.get("reasons") or []) or report.get("error") or "The update was refused."
    return HTTPStatus.CONFLICT, {**report, "error": message}
