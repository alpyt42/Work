"""Paths, the sibling tools this app reuses, shared constants, the request error and the input checks."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import threading
import unicodedata
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

# The folder of this app (tools/tasks-web/), the checkout that holds tools/ (the scripts run from here), and the Work root whose
# brains are served: WORK_DIR when set (like the other tools), else the same checkout.
APP_DIR = Path(__file__).resolve().parents[1]
TOOLS_ROOT = APP_DIR.parents[1]
WORK = Path(os.environ.get("WORK_DIR", TOOLS_ROOT)).resolve()
# Every write to an action register goes through tools/brain/action.py, run as a command (the same tool
# the agents use); reads import it, so the parsing is shared too.
ACTION_SCRIPT = TOOLS_ROOT / "tools/brain/action.py"
# Archiving a whole project or client, and bringing it back, is `tools/brain/brain-state.py archive|unarchive`, run as a command
# (the same tool and the same refusals as for the agents, see `Store.archive_change`).
BRAIN_STATE_SCRIPT = TOOLS_ROOT / "tools/brain/brain-state.py"
_spec = importlib.util.spec_from_file_location("brain_action", ACTION_SCRIPT)
assert _spec and _spec.loader
action_tool = importlib.util.module_from_spec(_spec)
sys.modules["brain_action"] = action_tool
_spec.loader.exec_module(action_tool)
# The rule of what a brain is and which one is the default lives in tools/machine/work_config.py.
_config_spec = importlib.util.spec_from_file_location("work_config", TOOLS_ROOT / "tools/machine/work_config.py")
assert _config_spec and _config_spec.loader
work_config = importlib.util.module_from_spec(_config_spec)
_config_spec.loader.exec_module(work_config)
# Where uv is on each system (the launcher's rule), for the Tools view.
_launch_spec = importlib.util.spec_from_file_location("tasks_launch", APP_DIR / "launch.py")
assert _launch_spec and _launch_spec.loader
tasks_launch = importlib.util.module_from_spec(_launch_spec)
_launch_spec.loader.exec_module(tasks_launch)
# The push checks own the rule that hides the credentials of a remote URL: the Sync view shows URLs the same way.
_push_spec = importlib.util.spec_from_file_location("preflight_push", TOOLS_ROOT / "tools/machine/preflight-push.py")
assert _push_spec and _push_spec.loader
preflight_push = importlib.util.module_from_spec(_push_spec)
_push_spec.loader.exec_module(preflight_push)
# What the checks of the brain call a Markdown link, and how they resolve one, is shared with "delete a note" (the pages that link to it): so that a deletion
# never leaves the link the next save would be refused for. The module reads a brain when it loads; only its link rules are used here.
_links_spec = importlib.util.spec_from_file_location("check_links", TOOLS_ROOT / "tools/brain/check-links.py")
assert _links_spec and _links_spec.loader
check_links = importlib.util.module_from_spec(_links_spec)
_links_brain = os.environ.get("BRAIN_DIR")
os.environ["BRAIN_DIR"] = str(TOOLS_ROOT)
try:
    _links_spec.loader.exec_module(check_links)
finally:
    if _links_brain is None:
        del os.environ["BRAIN_DIR"]
    else:
        os.environ["BRAIN_DIR"] = _links_brain
ACTION_STATUS = {"bad_request": HTTPStatus.BAD_REQUEST, "not_found": HTTPStatus.NOT_FOUND, "conflict": HTTPStatus.CONFLICT}
SUBTASKS_ROUTE = re.compile(r"/api/actions/([A-Z]{2,5}-\d{3})/subtasks")  # POST: add a subtask
SUBTASK_ROUTE = re.compile(r"/api/actions/([A-Z]{2,5}-\d{3})/subtasks/(\d{1,2})")  # PATCH: tick, rename or move it; DELETE: remove it
# Where archived folders are, below `projects/` (see action.py `live_parts`): a whole client, a client mission, an internal project,
# and the two earlier places; and the order of their kinds in the Archives view.
ARCHIVE_PLACES = ("clients/archive/*", "clients/*/missions/archive/*", "internal/archive/*", "archive/*", "clients/*/archive/*")
ARCHIVE_KINDS = ("client", "mission", "internal")
ARCHIVE_VERBS = {"/api/archives/archive": "archive", "/api/archives/unarchive": "unarchive"}
ASSETS = APP_DIR / "static"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUE_NOTE_RE = re.compile(r"-\s*due\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)
STATUS = {" ", "/", "w", "x", "-"}
PRIORITY = {"", "⏫", "🔼", "🔽"}
UNDO_LIMIT = 20
NOTE_TITLE_LIMIT = 150
NOTE_CONTENT_LIMIT = 100 * 1024
NOTE_REQUEST_LIMIT = 128 * 1024
NOTE_SUMMARY_READ = 16384
NOTE_EXCERPT_LIMIT = 160
NOTE_BACKLINK_LIMIT = 50  # pages listed when a note is still linked (the count is exact)
NOTE_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-|$)")
INBOX_DIR = "inbox"
INBOX_FILE = "inbox.md"  # the capture scratchpad of inbox/, triaged line by line: not a note
INBOX_LABEL = "Inbox"
INBOX_REGISTER = "inbox"  # wire value of `register` for a note left in the root inbox, to be sorted later
# What the interface writes into a brain file: the source of an action created from the interface and the
# header of a new note.
SOURCE_ENTERED = "entered in the local interface"
NOTE_HEADER = {"note": "Note from", "project": "project: ", "register": "register", "triage": "to triage"}
WRITE_LOCK = threading.Lock()
TOOL_LOCK = threading.Lock()


def python_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of a Python child: UTF-8 mode, so its pipes are UTF-8 on Windows too (the ANSI code page otherwise)."""
    return tasks_launch.utf8_environment(base)


class TaskError(Exception):
    def __init__(self, status: HTTPStatus, message: str, **extra: object) -> None:
        self.status = status
        self.message = message
        self.extra = extra  # more fields for the answer of a write that was refused (the pages that link to a note)
        super().__init__(message)


def parse_date(value: object, field: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"{field} must use the format YYYY-MM-DD.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise TaskError(HTTPStatus.BAD_REQUEST, f"{field} is not a valid date.") from error
    return value


def optional_date(value: object, field: str) -> str:
    return "" if value == "" else parse_date(value, field)


def clean_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"{field} is required.")
    value = value.strip()
    if not value or len(value) > limit or any(char in value for char in "\r\n\x00"):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"{field} must be 1 to {limit} characters on one line.")
    if (field == "Owner" and " — " in value) or any(marker in value for marker in ("➕", "📅", "⏳", "⏫", "🔼", "🔽", "✅", "❌")):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"{field} contains a separator reserved for registers.")
    return value


def clean_group(value: object) -> str:
    """A group slug (same rule as action.py), or '' for none."""
    slug = value.strip() if isinstance(value, str) else None
    if slug is None or (slug and not action_tool.valid_group(slug)):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"Invalid group: lowercase letters, digits and hyphens, {action_tool.GROUP_LIMIT} characters at most.")
    return slug


def clean_note(value: object) -> str:
    if not isinstance(value, str):
        raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note.")
    note = value.strip()
    if not note or len(note) > 1000 or note.splitlines() != [note] or "\x00" in note:
        raise TaskError(HTTPStatus.BAD_REQUEST, "The note must be 1 to 1000 characters on one line.")
    return note


def slugify(title: str) -> str:
    text = title.lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60].strip("-")
    return text or "note"


def clean_note_title(value: object) -> str:
    if not isinstance(value, str):
        raise TaskError(HTTPStatus.BAD_REQUEST, "Title required.")
    value = value.strip()
    if not value or len(value) > NOTE_TITLE_LIMIT or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"The title must be 1 to {NOTE_TITLE_LIMIT} characters on one line.")
    return value


def clean_note_content(value: object, required: bool) -> str:
    """Normalize line endings and enforce size and character limits; the result ends with one newline (or is empty)."""
    if not isinstance(value, str):
        raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid content.")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text or any(unicodedata.category(char) == "Cs" for char in text):
        raise TaskError(HTTPStatus.BAD_REQUEST, "The content contains disallowed characters.")
    if required and not text.strip():
        raise TaskError(HTTPStatus.BAD_REQUEST, "The content cannot be empty.")
    text = text.rstrip() + "\n" if text.strip() else ""
    if len(text.encode("utf-8")) > NOTE_CONTENT_LIMIT:
        raise TaskError(HTTPStatus.BAD_REQUEST, f"The content exceeds {NOTE_CONTENT_LIMIT // 1024} KB.")
    return text


def note_label(title: str, verb: str) -> str:
    short = title if len(title) <= 40 else title[:40].rstrip() + "…"
    return f'note "{short}" {verb}'


def note_summary(text: str, fallback: str) -> tuple[str, str]:
    """Title (first ``# `` heading, else ``fallback``) and a one-line excerpt of the body that follows it."""
    lines = text.splitlines()
    title = fallback
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("# ") and line[2:].strip():
            title, start = line[2:].strip(), index + 1
            break
    body = lines[start:]
    while body and (not body[0].strip() or body[0].lstrip().startswith(">")):
        body.pop(0)
    excerpt = " ".join(" ".join(body).split())
    if len(excerpt) > NOTE_EXCERPT_LIMIT:
        excerpt = excerpt[:NOTE_EXCERPT_LIMIT].rstrip() + "…"
    return title, excerpt


def doc_date(name: str, mtime: float) -> str:
    """The `YYYY-MM-DD` prefix of a file name when it is a real date, else the modification day (Europe/Paris)."""
    match = NOTE_DATE_PREFIX_RE.match(name)
    if match:
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
            return match.group(1)
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime, ZoneInfo("Europe/Paris")).date().isoformat()


def doc_type(relative: str, project: str, inbox: bool = False) -> str | None:
    """The type of a document from its path under the folder of its project (or under `inbox/`): note, source, workstream, journal or page; None for the rest.

    Notes are the files `notes/*.md` of a project and `inbox/*.md`, README files and the inbox scratchpad apart: the rule of `Store.notes()`.
    """
    parts = relative.split("/")
    name = parts[-1].lower()
    if inbox:
        return "note" if len(parts) == 1 and name not in {"readme.md", INBOX_FILE} else None
    if parts[0] == "notes" and len(parts) == 2:
        return None if name == "readme.md" else "note"
    if parts[0] == "sources" and len(parts) > 1:
        return None if name in {"index.md", "readme.md"} else "source"
    if parts[0] == "workstreams" and len(parts) > 1:
        return None if name == "readme.md" else "workstream"
    if parts[0] == "journal" and len(parts) == 2:
        return "journal"
    return "page" if len(parts) == 1 and parts[0] == f"{project}.md" else None


parse_action = action_tool.parse_action
