"""Notes of a Store: list, read, create, edit, tick a task box and delete."""

from __future__ import annotations

import hashlib
import posixpath
import re
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from .common import (
    INBOX_DIR, INBOX_FILE, INBOX_LABEL, INBOX_REGISTER, NOTE_BACKLINK_LIMIT, NOTE_CONTENT_LIMIT, NOTE_HEADER, NOTE_SUMMARY_READ, TaskError,
    UNDO_LIMIT, check_links, clean_note_content, clean_note_title, doc_date, note_label, note_summary, slugify,
)
from .markdown import TASK_LINE_RE


class NotesMixin:
    """The notes of a brain, mixed into `Store`: list, read, create, edit, tick a task box and delete."""

    def _project_dirs(self) -> list[dict]:
        return [{"dir": info["file"].parent.parent, "register": info["path"], "label": info["label"]} for info in self._scan_registers()]

    def _note_safe(self, path: Path, *, directory: bool = False) -> bool:
        try:
            return not path.is_symlink() and (path.is_dir() if directory else path.is_file()) and path.resolve().is_relative_to(self.brain)
        except OSError:
            return False

    @staticmethod
    def _note_date(path: Path) -> str:
        return doc_date(path.name, path.stat().st_mtime)

    def _note_files(self) -> list[tuple[Path, str, str]]:
        """Note files as (path, project label, register path); symlinks, archives, README files and the inbox scratchpad are skipped. Inbox notes use INBOX_REGISTER."""
        found = []
        folders = [(project["dir"] / "notes", project["label"], project["register"]) for project in self._project_dirs()]
        for folder, label, register in [*folders, (self.brain / INBOX_DIR, INBOX_LABEL, INBOX_REGISTER)]:
            if not self._note_safe(folder, directory=True):
                continue
            for path in sorted(folder.glob("*.md")):
                skipped = {"readme.md", INBOX_FILE} if register == INBOX_REGISTER else {"readme.md"}
                if path.name.lower() not in skipped and not path.name.startswith(".") and self._note_safe(path):
                    found.append((path, label, register))
        return found

    def notes(self) -> dict:
        items = []
        for path, label, register in self._note_files():
            try:
                with path.open("rb") as handle:
                    head = handle.read(NOTE_SUMMARY_READ).decode("utf-8", "replace")
                info = path.stat()
                title, excerpt = note_summary(head, path.stem)
                items.append({
                    "id": path.relative_to(self.brain).as_posix(), "title": title, "project": label, "register": register,
                    "date": self._note_date(path), "modified": datetime.fromtimestamp(info.st_mtime, ZoneInfo("Europe/Paris")).isoformat(timespec="seconds"),
                    "excerpt": excerpt, "size": info.st_size,
                })
            except OSError:
                continue
        items.sort(key=lambda item: item["title"].casefold())
        items.sort(key=lambda item: item["date"], reverse=True)
        return {"notes": items}

    def _note_entry(self, note_id: object) -> tuple[Path, str, str]:
        if isinstance(note_id, str):
            for path, label, register in self._note_files():
                if path.relative_to(self.brain).as_posix() == note_id:
                    return path, label, register
        raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.")

    def _note_payload(self, path: Path, label: str, register: str, data: bytes) -> dict:
        text = data.decode("utf-8", "replace")
        return {"id": path.relative_to(self.brain).as_posix(), "title": note_summary(text, path.stem)[0], "project": label, "register": register,
                "content": text, "deletable": True, "version": hashlib.sha256(data).hexdigest()[:16]}

    def note_content(self, note_id: object) -> dict:
        path, label, register = self._note_entry(note_id)
        try:
            return self._note_payload(path, label, register, path.read_bytes())
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.") from None

    def _note_header(self, project_dir: Path | None, label: str, today: str) -> str:
        words = NOTE_HEADER
        date = f"{today[8:10]}/{today[5:7]}/{today[:4]}"
        if project_dir is None:
            return f"> {words['note']} {date} · {words['triage']}"
        name = project_dir.name
        page = project_dir / f"{name}.md"
        if self._note_safe(page):
            target, text = f"../{quote(name)}.md", label
        else:
            target, text = "../state/actions.md", f"{label} ({words['register']})"
        text = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        return f"> {words['note']} {date} · {words['project']}[{text}]({target})"

    def _note_write(self, path: Path, before: bytes | None, after: bytes, label: str, created_dirs: list[Path] | None) -> None:
        self._atomic(path, after)
        self.undo_stack.append({"path": path, "before": before, "after": after, "label": label, "action_id": path.relative_to(self.brain).as_posix(),
                                "note": True, "created_dirs": created_dirs or []})
        del self.undo_stack[:-UNDO_LIMIT]

    def create_note(self, payload: dict) -> dict:
        if set(payload) != {"title", "register", "content"}:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note data.")
        title = clean_note_title(payload["title"])
        content = clean_note_content(payload["content"], required=False)
        if payload["register"] == INBOX_REGISTER:
            project_dir, label, register = None, INBOX_LABEL, INBOX_REGISTER
            folder = self.brain / INBOX_DIR
        else:
            known = {info["path"]: info for info in self._scan_registers()}
            info = known.get(payload["register"]) if isinstance(payload["register"], str) else None
            if info is None:
                raise TaskError(HTTPStatus.BAD_REQUEST, "Unknown project.")
            project_dir, label, register = info["file"].parent.parent, info["label"], info["path"]
            folder = project_dir / "notes"
        today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
        slug = slugify(title)
        text = f"# {title}\n\n{self._note_header(project_dir, label, today)}\n" + (f"\n{content}" if content else "")
        data = text.encode("utf-8")
        if len(data) > NOTE_CONTENT_LIMIT + 4096:
            raise TaskError(HTTPStatus.BAD_REQUEST, f"The content exceeds {NOTE_CONTENT_LIMIT // 1024} KB.")
        if (folder.exists() or folder.is_symlink()) and not self._note_safe(folder, directory=True):
            raise TaskError(HTTPStatus.CONFLICT, "The notes folder cannot be used.")
        created: list[Path] = []
        number = 1
        while True:
            suffix = "" if number == 1 else f"-{number}"
            path = folder / f"{today}-{slug}{suffix}.md"
            if not (path.exists() or path.is_symlink()):
                break
            number += 1
        try:
            for directory in reversed([parent for parent in (path.parent, *path.parent.parents) if not parent.exists() and parent.is_relative_to(self.brain)]):
                directory.mkdir()
                created.append(directory)
            self._note_write(path, None, data, note_label(title, "created"), list(reversed(created)))
        except OSError:
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    break
            raise
        return {"id": path.relative_to(self.brain).as_posix(), "note": self._note_payload(path, label, register, data)}

    def update_note(self, payload: dict) -> dict:
        if set(payload) != {"id", "version", "content"} or not isinstance(payload["version"], str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note data.")
        content = clean_note_content(payload["content"], required=True)
        path, _, _ = self._note_entry(payload["id"])
        try:
            before = path.read_bytes()
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.") from None
        if payload["version"] != hashlib.sha256(before).hexdigest()[:16]:
            raise TaskError(HTTPStatus.CONFLICT, "The note changed on disk. Reload it before retrying.")
        after = content.encode("utf-8")
        if after != before:
            self._note_write(path, before, after, note_label(note_summary(content, path.stem)[0], "edited"), None)
        return {"id": path.relative_to(self.brain).as_posix(), "version": hashlib.sha256(after).hexdigest()[:16]}

    def toggle_task(self, payload: dict) -> dict:
        """Tick or untick one `[ ]` / `[x]` box of a working note: one byte changes, one undo step."""
        if (set(payload) != {"id", "version", "line", "done"} or not isinstance(payload["id"], str) or not isinstance(payload["version"], str)
                or isinstance(payload["line"], bool) or not isinstance(payload["line"], int) or payload["line"] < 0 or not isinstance(payload["done"], bool)):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note data.")
        path, _, _ = self._note_entry(payload["id"])
        try:
            before = path.read_bytes()
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.") from None
        stale = TaskError(HTTPStatus.CONFLICT, "The note changed on disk. Reload it before retrying.")
        if payload["version"] != hashlib.sha256(before).hexdigest()[:16]:
            raise stale
        lines = before.split(b"\n")
        if payload["line"] >= len(lines):
            raise TaskError(HTTPStatus.BAD_REQUEST, "No checkbox on that line.")
        match = TASK_LINE_RE.match(lines[payload["line"]])
        if not match:
            raise TaskError(HTTPStatus.BAD_REQUEST, "No checkbox on that line.")
        if (match.group(2) != b" ") == payload["done"]:
            raise stale
        lines[payload["line"]] = lines[payload["line"]][:match.start(2)] + (b"x" if payload["done"] else b" ") + lines[payload["line"]][match.end(2):]
        after = b"\n".join(lines)
        self._note_write(path, before, after, note_label(note_summary(before.decode("utf-8", "replace"), path.stem)[0], "box ticked" if payload["done"] else "box unticked"), None)
        return {"id": path.relative_to(self.brain).as_posix(), "version": hashlib.sha256(after).hexdigest()[:16]}

    # --- Deleting a note ---------------------------------------------------------------------------------

    def _deletable_note(self, note_id: object) -> Path:
        """The file of a working note (`<project>/notes/*.md` or an inbox note, as `_note_files` lists them), else a refusal.

        Nothing else is ever deletable here: not a source, a project page, a register, `docs/`, `me/`, `people/`, `tasks.md`, a file
        outside the brain, a symbolic link. The id is only compared with the notes found, never turned into a path.
        """
        try:
            return self._note_entry(note_id)[0]
        except TaskError:
            if isinstance(note_id, str) and any(entry.id == note_id for entry in self.docs()):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Only a working note can be deleted from here.") from None
            raise

    def note_backlinks(self, note_id: str) -> list[dict]:
        """The pages of the brain that link to a note: what the next check of links would report as dead once it is gone.

        Uses the rules of tools/brain/check-links.py: Markdown links to a `.md` file, with or without an `#anchor`, resolved from the folder
        of the page, and `[[wikilinks]]` by file name when no other file has that name. Code is ignored, like there. The note itself is not a page
        that blocks its own deletion.
        """
        base = posixpath.basename(note_id)[:-3]
        entries = self.docs()
        wiki_breaks = not any(entry.id != note_id and posixpath.basename(entry.id)[:-3] == base for entry in entries)
        projects = self._doc_projects()
        pages = []
        for entry in entries:
            name = posixpath.basename(entry.id)
            if entry.id == note_id or check_links.is_skill_asset(entry.id) or (name.startswith("_") and "TEMPLATE" in entry.id):
                continue
            text = check_links.mask_code(entry.text)
            linked = False
            if wiki_breaks:
                for raw in check_links.WIKILINK.findall(text):
                    target = re.split(r"\\?\|", raw)[0].strip().rstrip("\\")
                    stem = posixpath.basename(target)
                    stem = stem[:-3] if stem.endswith(".md") else stem
                    if "<" not in target and stem == base:
                        linked = True
                        break
            if not linked:
                for target in check_links.MDLINK.findall(text):
                    if target.startswith(("http", "#", "mailto:")) or check_links.SCHEME.match(target):
                        continue
                    target = target.split("#")[0]
                    if not target.endswith(".md") or "<" in target or "YYYY" in target:
                        continue
                    folder = posixpath.dirname(entry.id)
                    if note_id in (posixpath.normpath(posixpath.join(folder, target)), posixpath.normpath(posixpath.join(folder, unquote(target)))):
                        linked = True
                        break
            if linked:
                owner = self._doc_project(entry.id, projects)
                pages.append({"id": entry.id, "title": entry.title, "project": owner[0] if owner else None})
        pages.sort(key=lambda page: page["id"])
        return pages

    def note_links(self, note_id: object) -> dict:
        """What the page needs to confirm a deletion: the note and the pages that still link to it."""
        path, label, register = self._note_entry(note_id)
        try:
            payload = self._note_payload(path, label, register, path.read_bytes())
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.") from None
        pages = self.note_backlinks(payload["id"])
        return {"id": payload["id"], "title": payload["title"], "version": payload["version"], "count": len(pages), "pages": pages[:NOTE_BACKLINK_LIMIT]}

    def delete_note_file(self, payload: dict) -> dict:
        """Delete a working note, if it is the version the person saw and no page links to it; one undo step brings its bytes back."""
        if set(payload) != {"id", "version"} or not isinstance(payload["id"], str) or not isinstance(payload["version"], str):
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid note data.")
        path = self._deletable_note(payload["id"])
        try:
            before = path.read_bytes()
            mode = path.stat().st_mode & 0o777
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.") from None
        if payload["version"] != hashlib.sha256(before).hexdigest()[:16]:
            raise TaskError(HTTPStatus.CONFLICT, "The note changed on disk. Reload it before deleting it.")
        note_id = path.relative_to(self.brain).as_posix()
        pages = self.note_backlinks(note_id)
        if pages:
            raise TaskError(HTTPStatus.CONFLICT, f"This note is linked from {len(pages)} {'page' if len(pages) == 1 else 'pages'}. Remove those links first, or ask your agent.",
                            backlinks=pages[:NOTE_BACKLINK_LIMIT], count=len(pages))
        title = note_summary(before.decode("utf-8", "replace"), path.stem)[0]
        path.unlink()
        self.undo_stack.append({"path": path, "before": before, "after": None, "label": note_label(title, "deleted"), "action_id": note_id,
                                "note": True, "deleted": True, "mode": mode})
        del self.undo_stack[:-UNDO_LIMIT]
        return {"deleted": note_id, "title": title}
