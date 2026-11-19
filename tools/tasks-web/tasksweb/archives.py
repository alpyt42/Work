"""Archives of a Store: list and read the archived projects, archive and unarchive one."""

from __future__ import annotations

import json
import posixpath
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path

from .common import (
    ARCHIVE_KINDS, ARCHIVE_PLACES, BRAIN_STATE_SCRIPT, DATE_RE, TaskError, UNDO_LIMIT, action_tool, doc_date, python_environment, work_config,
)
from .brains import client_names
from .git_sync import run_git


class ArchivesMixin:
    """The archived projects of a brain, mixed into `Store`.

    An archived project or client (moved whole into the `archive/` folder at its level by `brain-state.py archive`) is out of every
    view and search; the Archives view alone lists and reads them, read-only. Archiving and unarchiving run that tool: a dry run to
    show what moves (or what blocks), then the write, one undo step whose undo is the inverse command.
    """

    def _archived_registers(self) -> list[Path]:
        return [path for path in action_tool.registers(self.brain) if self.archived(path)]

    def archive_roots(self) -> list[Path]:
        """The archived folders, each one what `unarchive` brings back: a whole client, a client mission, an internal project (the
        earlier places `projects/archive/<p>` and `projects/clients/<c>/archive/<m>` too). A mission inside an archived client is part of it."""
        roots: set[Path] = set()
        for pattern in ARCHIVE_PLACES:
            for folder in self.projects.glob(pattern):
                if (folder.name != "archive" and not folder.name.startswith(".") and folder.is_dir() and not folder.is_symlink()
                        and action_tool.archived_root(folder, self.brain) == folder):
                    roots.add(folder)
        return sorted(roots, key=lambda root: (ARCHIVE_KINDS.index(self._archive_kind(root)), self._archive_label(root)))

    def _archive_kind(self, folder: Path) -> str:
        """`client`, `mission` or `internal`, as the folder reads out of the archive."""
        parts = action_tool.live_parts(folder.relative_to(self.projects).parts)
        return "client" if parts[:1] == ("clients",) and len(parts) == 2 else "mission" if parts[:1] == ("clients",) else "internal"

    def _archive_label(self, folder: Path) -> str:
        """The label of an archived folder as a live one reads (`client / mission`, the project, the client), by folder names."""
        parts = action_tool.live_parts(folder.relative_to(self.projects).parts)
        return f"{parts[1]} / {parts[3]}" if parts[:1] == ("clients",) and len(parts) >= 4 else parts[-1]

    def _archived_on(self, folder: Path) -> str | None:
        """The day Git saw the folder's files appear where they are (the commit of the move); None without Git or before it is saved."""
        if not (self.brain / ".git").exists():
            return None
        try:
            day = run_git(self.brain, "log", "-1", "--format=%cs", "--diff-filter=A", "--", folder.relative_to(self.brain).as_posix())
        except TaskError:
            return None
        day = day.decode("utf-8", "replace").strip()
        return day if DATE_RE.match(day) else None

    @staticmethod
    def _archived_action(entry: dict, folder: str) -> dict:
        return {**{key: entry[key] for key in ("id", "title", "owner", "state", "done", "due", "project", "register", "group", "priority")},
                "folder": folder, **({"subtasks": entry["subtasks"]} if "subtasks" in entry else {})}

    def archives(self) -> dict:
        """`GET /api/archives`: each archived folder (`folder`, `kind`, `label` by folder names, `client`, `archived_on`, its `projects`
        and the `counts` of its actions), every archived action (for the search of the view) and the display names of the clients."""
        registers = self._archived_registers()
        items, actions = [], []
        for root in self.archive_roots():
            folder = root.relative_to(self.brain).as_posix()
            mine = [path for path in registers if path.is_relative_to(root)]
            entries = [entry for path in mine for entry in action_tool.load(path, self.brain)]
            done = sum(entry["state"] == "x" for entry in entries)
            cancelled = sum(entry["state"] == "-" for entry in entries)
            parts = action_tool.live_parts(root.relative_to(self.projects).parts)
            items.append({"folder": folder, "kind": self._archive_kind(root), "label": self._archive_label(root),
                          "client": parts[1] if parts[:1] == ("clients",) else "", "archived_on": self._archived_on(root),
                          "projects": [{"register": path.relative_to(self.brain).as_posix(), "label": action_tool.project_label(path, self.brain)} for path in mine],
                          "counts": {"total": len(entries), "done": done, "cancelled": cancelled, "open": len(entries) - done - cancelled}})
            actions += [self._archived_action(entry, folder) for entry in entries]
        return {"archives": items, "actions": actions, "clients": client_names(self.brain)}

    def _archive_folder(self, value: object, archived: bool) -> Path:
        """The folder a request names (brain-relative, `projects/…`): an archived root for ``archived``, else a live project (one with a
        register) or a live client. Anything else, a path that climbs out or a link included, is refused."""
        if not isinstance(value, str) or not value.startswith("projects/") or "\\" in value or "\x00" in value:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid project folder.")
        value = value.rstrip("/")
        if any(part in {"", ".", ".."} for part in value.split("/")):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid project folder.")
        if archived:
            known = {root.relative_to(self.brain).as_posix(): root for root in self.archive_roots()}
        else:
            known = {path.parent.parent.relative_to(self.brain).as_posix(): path.parent.parent for path in self.registers()}
            clients = self.projects / "clients"
            for folder in (sorted(clients.iterdir()) if clients.is_dir() and not clients.is_symlink() else []):
                if folder.is_dir() and not folder.is_symlink() and not folder.name.startswith(".") and folder.name != "archive":
                    known[folder.relative_to(self.brain).as_posix()] = folder
        folder = known.get(value)
        if folder is None:
            raise TaskError(HTTPStatus.NOT_FOUND, "Archived project not found." if archived else "Project not found.")
        return folder

    def archive_project(self, value: object) -> dict:
        """`GET /api/archives/project?folder=`: an archived folder to read: its page, and for each of its projects the page, the
        decisions (`state/decisions.md`, read as a document) and the actions; and its documents of the Docs types, newest first."""
        root = self._archive_folder(value, archived=True)
        folder = root.relative_to(self.brain).as_posix()
        catalogue = {entry.id: entry for entry in self.docs(archived=True)}

        def page(directory: Path) -> str | None:
            doc_id = (directory / f"{directory.name}.md").relative_to(self.brain).as_posix()
            return doc_id if doc_id in catalogue else None

        projects = []
        for path in (path for path in self._archived_registers() if path.is_relative_to(root)):
            directory = path.parent.parent
            decisions = (directory / "state/decisions.md").relative_to(self.brain).as_posix()
            projects.append({"register": path.relative_to(self.brain).as_posix(), "label": action_tool.project_label(path, self.brain),
                             "folder": directory.relative_to(self.brain).as_posix(), "page": page(directory) if directory != root else None,
                             "decisions": decisions if decisions in catalogue else None,
                             "actions": action_tool.load(path, self.brain)})
        owners = self._doc_projects(archived=True)
        folders = {register: owner_folder for owner_folder, _, register in owners}
        docs = []
        for entry in catalogue.values():
            if not entry.id.startswith(folder + "/"):
                continue
            owner = self._doc_project(entry.id, owners)
            kind = self._doc_kind(entry.id, owner, folders)
            if kind is not None:
                docs.append({"id": entry.id, "title": entry.title, "type": kind, "project": owner[0] if owner else None,
                             "date": doc_date(posixpath.basename(entry.id), entry.mtime)})
        docs.sort(key=lambda item: item["title"].casefold())
        docs.sort(key=lambda item: item["date"], reverse=True)
        return {"folder": folder, "kind": self._archive_kind(root), "label": self._archive_label(root), "archived_on": self._archived_on(root),
                "page": page(root), "projects": projects, "docs": docs}

    def _run_archive(self, verb: str, folder: Path, write: bool) -> dict:
        """`brain-state.py archive|unarchive <folder> --brain <name> --json [--write]`, on the Work this brain sits in.

        Run as a command, as action.py is for the actions: the tool owns the rules (finished projects only, `internal/setup` never, the
        links to rewrite, the exact inverse) and says its refusals in its own words; a 400 carries them, a 409 when open actions block
        it (with their list) or the place is taken."""
        if not work_config.is_brain(self.brain):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Archiving needs a brain of a Work (a folder holding AGENTS.md and .data/).")
        argv = [sys.executable, str(BRAIN_STATE_SCRIPT), verb, str(folder), "--brain", self.brain.name, "--json", *(["--write"] if write else [])]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False, stdin=subprocess.DEVNULL,
                                    env={**python_environment(), "WORK_DIR": str(self.brain.parent)})
        except (OSError, subprocess.TimeoutExpired):
            raise TaskError(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not run the archive tool.") from None
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else None
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("refused") == "open actions":
            still = payload.get("open_actions") or []
            raise TaskError(HTTPStatus.CONFLICT, f"{payload.get('project', 'This project')} cannot be archived: {len(still)} "
                            f"{'action is' if len(still) == 1 else 'actions are'} still to do, in progress or waiting. Close or cancel "
                            f"{'it' if len(still) == 1 else 'them'} first, then archive again.",
                            open_actions=[{key: item.get(key, "") for key in ("id", "state", "title", "project")} for item in still])
        if not isinstance(payload, dict) or "to" not in payload:
            lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
            message = lines[-1] if lines else f"The archive tool failed (exit {result.returncode})."
            raise TaskError(HTTPStatus.CONFLICT if "already exists" in message else HTTPStatus.BAD_REQUEST, message[:1].upper() + message[1:])
        return payload

    def _archive_summary(self, payload: dict) -> dict:
        """What the page shows of an archive or unarchive: what moves where, the links rewritten, the mentions left, the link check."""
        def local(shown: str) -> str:
            return shown.split("/", 1)[1] if "/" in shown else shown
        check = payload.get("link_check")
        return {"verb": payload["command"], "kind": payload["kind"], "label": payload["project"], "from": local(payload["from"]),
                "to": local(payload["to"]), "write": payload["write"], "files_changed": payload["files_changed"],
                "links": len(payload["links"]), "link_files": sorted({item["file"] for item in payload["links"]}),
                "mentions_left": payload["mentions_left"], "created_dirs": [local(item) for item in payload["created_dirs"]],
                "removed_dirs": [local(item) for item in payload["removed_dirs"]],
                "link_check": None if check is None else {"ok": check.get("exit") == 0, "problems": check.get("problems", [])[:10]}}

    def archive_plan(self, verb: str, value: object) -> dict:
        """`GET /api/archives/plan?verb=archive|unarchive&folder=`: the dry run, nothing moves."""
        return self._archive_summary(self._run_archive(verb, self._archive_folder(value, archived=verb == "unarchive"), write=False))

    def archive_write(self, verb: str, payload: dict) -> dict:
        """`POST /api/archives/archive|unarchive` {folder}: moves it (the tool checks everything again) and stacks the inverse as its undo."""
        if set(payload) != {"folder"}:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid archive data.")
        folder = self._archive_folder(payload["folder"], archived=verb == "unarchive")
        summary = self._archive_summary(self._run_archive(verb, folder, write=True))
        self._doc_cache.clear()
        self._archive_cache.clear()
        self.undo_stack.append({"command": "unarchive" if verb == "archive" else "archive", "path": self.brain / summary["to"],
                                "label": f"{verb} of {summary['label']}", "action_id": None})
        del self.undo_stack[:-UNDO_LIMIT]
        return summary

    def _undo_archive(self, entry: dict) -> dict:
        """The undo of an archive or unarchive: the inverse command on the folder where the move left it (refused when it is gone)."""
        folder = entry["path"]
        if not folder.is_dir() or folder.is_symlink():
            self.undo_stack[:] = [item for item in self.undo_stack if item is not entry]
            raise TaskError(HTTPStatus.CONFLICT, "The folder moved since; this cannot be undone.")
        try:
            self._run_archive(entry["command"], folder, write=True)
        except TaskError:
            self.undo_stack[:] = [item for item in self.undo_stack if item is not entry]  # refused (an action reopened meanwhile): dropped
            raise
        self._doc_cache.clear()
        self._archive_cache.clear()
        self.undo_stack.pop()
        return {"undone": entry["label"], "action_id": None, "undo": self.undo_state()}
