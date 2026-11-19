"""The Store: the actions of one brain, their edits and the undo stack."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import (
    ACTION_SCRIPT, ACTION_STATUS, DUE_NOTE_RE, PRIORITY, SOURCE_ENTERED, STATUS, TaskError, UNDO_LIMIT, action_tool, clean_group, clean_note,
    clean_text, optional_date, python_environment,
)
from .brains import client_names
from .docs import DocEntry, DocsMixin
from .notes import NotesMixin
from .archives import ArchivesMixin


class Store(NotesMixin, DocsMixin, ArchivesMixin):
    """One brain: its actions and the undo stack (here), its notes, documents and archived projects (the mixins)."""

    def __init__(self, brain: Path) -> None:
        self.brain = brain.resolve()
        self.projects = self.brain / "projects"
        if not self.projects.is_dir():
            raise ValueError(f"Registers not found under {self.projects}")
        self.undo_stack: list[dict] = []
        self._doc_cache: dict[str, DocEntry] = {}
        self._archive_cache: dict[str, DocEntry] = {}  # the documents of the archived projects (the Archives view)
        self._doc_lock = threading.Lock()

    def archived(self, path: Path | str) -> bool:
        """True for a path inside an archived project (an `archive/` folder at its level, see `action.py` `live_parts`): the app never shows those."""
        return action_tool.in_archived_project(path, self.brain)

    def registers(self) -> list[Path]:
        """The registers of the ongoing projects (archived ones are skipped: they leave every view; only Sync, which reads Git, still sees them)."""
        root = self.projects.resolve()
        files = []
        for path in sorted(root.glob("**/state/actions.md")):
            if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file() or self.archived(path):
                continue
            files.append(path)
        return files

    def owner(self) -> str:
        config = self.brain / ".data/doctor.json"
        if config.is_file():
            try:
                return str(json.loads(config.read_text(encoding="utf-8")).get("owner", "")).strip()
            except (OSError, ValueError, TypeError):
                pass
        return os.environ.get("BRAIN_OWNER", "").strip()

    @staticmethod
    def _due_notes(path: Path, entries: list[dict]) -> None:
        """Give each action `due_note`: the wording of its `due:` sub-bullet when it has no 📅 date ("week of 05/10"), else "".
        The Timeline lists these as vague deadlines. A "—" (no deadline), or a register that changed meanwhile, gives an empty note."""
        for entry in entries:
            entry["due_note"] = ""
        pending = [entry for entry in entries if not entry["due"]]
        if not pending:
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return
        for entry in pending:
            index = entry["line"] - 1
            if index >= len(lines) or f"**{entry['id']}**" not in lines[index]:
                continue
            for start, end in action_tool.items(lines, index, action_tool.last_detail(lines, index)):
                match = DUE_NOTE_RE.match(action_tool.item_text(lines, start, end))
                if match:
                    note = " ".join(match.group(1).split())
                    entry["due_note"] = "" if note in {"", "—", "–", "-"} else note[:200]
                    break

    @staticmethod
    def _subtask_texts(path: Path, entries: list[dict]) -> None:
        """Add the texts of the steps to the `subtasks` progress `load()` gives an action that has subtasks ({done, total}):
        `texts`, in register order, so that the page searches them. A register that changed meanwhile gives an empty list."""
        pending = [entry for entry in entries if "subtasks" in entry]
        if not pending:
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        for entry in pending:
            index = entry["line"] - 1
            fresh = index < len(lines) and f"**{entry['id']}**" in lines[index]
            entry["subtasks"]["texts"] = [item["text"] for item in action_tool.subtasks_of(lines, index)] if fresh else []

    def _scan_registers(self) -> list[dict]:
        infos = []
        for path in self.registers():
            entries = action_tool.load(path, self.brain)
            self._due_notes(path, entries)
            self._subtask_texts(path, entries)
            label = entries[0]["project"] if entries else action_tool.project_label(path, self.brain)
            prefixes = {entry["id"].split("-", 1)[0] for entry in entries}
            infos.append({"file": path, "path": path.relative_to(self.brain).as_posix(), "label": label,
                          "prefix": next(iter(prefixes)) if len(prefixes) == 1 else "", "entries": entries,
                          "groups": sorted({entry["group"] for entry in entries if entry["group"]})})
        return infos

    def snapshot(self) -> dict:
        infos = self._scan_registers()
        actions = [action for info in infos for action in info["entries"]]
        registers = [{key: info[key] for key in ("path", "label", "prefix", "groups")} for info in infos]
        return {"actions": actions, "registers": registers, "owner": self.owner(), "today": datetime.now(ZoneInfo("Europe/Paris")).date().isoformat(),
                "clients": client_names(self.brain)}

    def _register(self, relative: object) -> Path:
        if not isinstance(relative, str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid project.")
        for path in self.registers():
            if path.relative_to(self.brain).as_posix() == relative:
                return path
        raise TaskError(HTTPStatus.BAD_REQUEST, "Unknown project.")

    def _find(self, action_id: str) -> tuple[Path, list[str], int, dict]:
        try:
            return action_tool.find(self.brain, action_id)
        except action_tool.ActionError as error:
            raise TaskError(ACTION_STATUS[error.kind], error.message) from None

    def details(self, action_id: str) -> dict:
        try:
            return action_tool.details(self.brain, action_id)
        except action_tool.ActionError as error:
            raise TaskError(ACTION_STATUS[error.kind], error.message) from None

    @staticmethod
    def _fields(data: dict) -> tuple[str, str, str, str, str, str, str | None]:
        # `group` is optional: absent means unchanged on update (a status change does not send it), none on create.
        if set(data) - {"group"} != {"title", "owner", "state", "priority", "due", "scheduled"}:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid action fields.")
        title = clean_text(data["title"], "Title", 300)
        owner = clean_text(data["owner"], "Owner", 120)
        state = data["state"]
        priority = data["priority"]
        if not isinstance(state, str) or not isinstance(priority, str) or state not in STATUS or priority not in PRIORITY:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid status or priority.")
        return (title, owner, state, priority, optional_date(data["due"], "Due date"), optional_date(data["scheduled"], "Scheduled date"),
                clean_group(data["group"]) if "group" in data else None)

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".actions-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def _run_action(self, path: Path, action_id: str | None, *argv: str) -> dict:
        """Run tools/brain/action.py and record the register's bytes before and after for one undo step."""
        before = path.read_bytes()
        try:
            result = subprocess.run([sys.executable, str(ACTION_SCRIPT), "--brain", str(self.brain), *argv], env=python_environment(),
                                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            payload = json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise TaskError(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not run the actions tool.") from None
        if result.returncode:
            raise TaskError(ACTION_STATUS.get(payload.get("kind"), HTTPStatus.INTERNAL_SERVER_ERROR), payload.get("error") or "The actions tool failed.")
        after = path.read_bytes()
        if after != before:
            self.undo_stack.append({"path": path, "before": before, "after": after, "label": payload["label"],
                                    "action_id": action_id or payload.get("id")})
            del self.undo_stack[:-UNDO_LIMIT]
        return payload

    def undo_state(self) -> dict:
        top = self.undo_stack[-1] if self.undo_stack else None
        return {"available": top is not None, "label": top["label"] if top else None, "depth": len(self.undo_stack)}

    def _restore_deleted_note(self, entry: dict) -> None:
        """Undo of a deletion: the bytes of the note come back at its path, with its mode, unless something is there now (then nothing is written)."""
        path = entry["path"]
        if path.exists() or path.is_symlink():
            self.undo_stack[:] = [item for item in self.undo_stack if item["path"] != path]
            raise TaskError(HTTPStatus.CONFLICT, "A file now exists where this note was: it cannot be restored.")
        created: list[Path] = []
        try:
            for directory in reversed([parent for parent in path.parents if not parent.exists() and parent.is_relative_to(self.brain)]):
                directory.mkdir()
                created.append(directory)
            if path.parent.is_symlink() or not path.parent.resolve().is_relative_to(self.brain):
                raise TaskError(HTTPStatus.CONFLICT, "The folder of this note can no longer be used: it cannot be restored.")
            self._atomic(path, entry["before"])
        except (OSError, TaskError):
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    break
            raise
        try:
            os.chmod(path, entry["mode"])
        except OSError:
            pass

    def undo(self, payload: dict) -> dict:
        if set(payload) != {"label"} or not isinstance(payload["label"], str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid undo data.")
        if not self.undo_stack:
            raise TaskError(HTTPStatus.CONFLICT, "Nothing to undo.")
        entry = self.undo_stack[-1]
        if payload["label"] != entry["label"]:
            raise TaskError(HTTPStatus.CONFLICT, "The last change is different. Refresh before undoing.")
        if entry.get("command"):  # an archive or an unarchive: its undo is the inverse command
            return self._undo_archive(entry)
        path = entry["path"]
        if entry.get("deleted"):
            self._restore_deleted_note(entry)
            self.undo_stack.pop()
            return {"undone": entry["label"], "action_id": entry["action_id"], "restored": True, "undo": self.undo_state()}
        try:
            current = path.read_bytes()
        except OSError:
            current = None
        if current != entry["after"]:
            self.undo_stack[:] = [item for item in self.undo_stack if item["path"] != path]
            raise TaskError(HTTPStatus.CONFLICT, f"The {'note' if entry.get('note') else 'register'} changed since this edit; it cannot be undone.")
        if entry["before"] is None:
            path.unlink()
            for directory in entry.get("created_dirs", []):
                try:
                    directory.rmdir()
                except OSError:
                    break
        else:
            self._atomic(path, entry["before"])
        self.undo_stack.pop()
        return {"undone": entry["label"], "action_id": entry["action_id"], "undo": self.undo_state()}

    @staticmethod
    def _field_args(fields: tuple[str, str, str, str, str, str, str | None]) -> list[str]:
        title, owner, state, priority, due, scheduled, group = fields
        return [f"--title={title}", f"--owner={owner}", f"--state={state}", f"--priority={priority}", f"--due={due}", f"--scheduled={scheduled}",
                *([] if group is None else [f"--group={group}"])]

    def create(self, payload: dict) -> dict:
        if set(payload) != {"register", "action"} or not isinstance(payload["action"], dict):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid creation data.")
        path = self._register(payload["register"])
        fields = self._fields(payload["action"])
        if fields[2] not in {" ", "/", "w"}:
            raise TaskError(HTTPStatus.BAD_REQUEST, "A new action must be to do, in progress or waiting.")
        today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
        result = self._run_action(path, None, "create", f"--project={payload['register']}", *self._field_args(fields),
                                  f"--source={SOURCE_ENTERED}, {today[8:10]}/{today[5:7]}")
        return {"id": result["id"]}

    def update(self, action_id: str, payload: dict) -> dict:
        if set(payload) != {"version", "action"} or not isinstance(payload["action"], dict):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid update data.")
        fields = self._fields(payload["action"])
        if not isinstance(payload["version"], str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid update data.")
        path = self._find(action_id)[0]
        result = self._run_action(path, action_id, "update", action_id, *self._field_args(fields), f"--expect-version={payload['version']}")
        # Closing an action whose subtasks are still open is allowed: the tool says so, and the page shows it.
        return {"id": action_id, **({"warnings": result["warnings"]} if result.get("warnings") else {})}

    def _locked(self, action_id: str, payload: dict, keys: set[str], what: str = "note") -> Path:
        if set(payload) != keys or not isinstance(payload["details_version"], str):
            raise TaskError(HTTPStatus.BAD_REQUEST, f"Invalid {what} data.")
        return self._find(action_id)[0]

    def add_note(self, action_id: str, payload: dict) -> dict:
        note = clean_note(payload.get("note"))
        path = self._locked(action_id, payload, {"details_version", "note"})
        result = self._run_action(path, action_id, "history", "add", action_id, f"--text={note}",
                                  f"--expect-details-version={payload['details_version']}")
        # The same note on the same day is written once: `unchanged` tells the page that nothing was added.
        return {**self.details(action_id), "unchanged": bool(result.get("unchanged"))}

    # Subtasks: the checklist of an action, written by `action.py subtask` under the details-version lock; each answer is the
    # refreshed details (like the history routes), and each write is one undo step. The tool's refusals (too many words, an
    # eleventh subtask, an index that is not there) come back as 400 with its message, a stale lock as 409.

    @staticmethod
    def _subtask_text(value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Subtask text is required.")
        return value.strip()

    def _subtask_run(self, path: Path, action_id: str, payload: dict, *argv: str) -> dict:
        result = self._run_action(path, action_id, "subtask", *argv, f"--expect-details-version={payload['details_version']}")
        return {**self.details(action_id), "unchanged": bool(result.get("unchanged"))}

    def add_subtask(self, action_id: str, payload: dict) -> dict:
        """`POST /api/actions/<ID>/subtasks` {details_version, text[, position]}: a new open subtask, last unless `position` (from 0)."""
        keys = {"details_version", "text"} | ({"position"} if "position" in payload else set())
        path = self._locked(action_id, payload, keys, "subtask")
        text = self._subtask_text(payload["text"])
        position = payload.get("position")
        if position is not None and (type(position) is not int or position < 0):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid subtask position.")
        return self._subtask_run(path, action_id, payload, "add", action_id, f"--text={text}",
                                 *([] if position is None else [f"--position={position}"]))

    def change_subtask(self, action_id: str, number: int, payload: dict) -> dict:
        """`PATCH /api/actions/<ID>/subtasks/<N>` {details_version} and one of: `done` (true ticks, false unticks: a subtask already
        in that state is left as is), `text` (renames it, state kept) or `to` (moves it to that index, from 0)."""
        change = set(payload) - {"details_version"}
        if len(change) != 1 or not change <= {"done", "text", "to"}:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid subtask data.")
        path = self._locked(action_id, payload, {"details_version", *change}, "subtask")
        if "done" in payload:
            if not isinstance(payload["done"], bool):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid subtask data.")
            return self._subtask_run(path, action_id, payload, "toggle", action_id, f"--index={number}",
                                     "--done" if payload["done"] else "--undone")
        if "text" in payload:
            text = self._subtask_text(payload["text"])
            return self._subtask_run(path, action_id, payload, "edit", action_id, f"--index={number}", f"--text={text}")
        if type(payload["to"]) is not int or payload["to"] < 0:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid subtask position.")
        return self._subtask_run(path, action_id, payload, "move", action_id, f"--index={number}", f"--to={payload['to']}")

    def remove_subtask(self, action_id: str, number: int, payload: dict) -> dict:
        """`DELETE /api/actions/<ID>/subtasks/<N>` {details_version}."""
        path = self._locked(action_id, payload, {"details_version"}, "subtask")
        return self._subtask_run(path, action_id, payload, "remove", action_id, f"--index={number}")

    def delete_note(self, action_id: str, number: int, payload: dict) -> dict:
        if not isinstance(payload.get("text"), str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note data.")
        path = self._locked(action_id, payload, {"details_version", "text"})
        self._run_action(path, action_id, "history", "remove", action_id, f"--index={number}", f"--expect-text={payload['text']}",
                         f"--expect-details-version={payload['details_version']}")
        return self.details(action_id)

    def delete_action(self, action_id: str, payload: dict) -> dict:
        if set(payload) != {"version", "details_version"} or not all(isinstance(payload[key], str) for key in payload):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid deletion data.")
        path = self._find(action_id)[0]
        self._run_action(path, action_id, "delete", action_id, f"--expect-version={payload['version']}",
                         f"--expect-details-version={payload['details_version']}")
        return {"deleted": action_id}
