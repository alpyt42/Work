"""Documents: the catalogue of a brain's Markdown files, search and rendering."""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from array import array
from bisect import bisect_left, bisect_right
from datetime import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo

from .common import INBOX_DIR, INBOX_LABEL, INBOX_REGISTER, TaskError, action_tool, doc_date, doc_type, note_summary
from .markdown import FENCE_RE, HEADING_RE, MARKDOWN, fold, fold_mapped, front_matter_html, split_front_matter

DOC_SIZE_LIMIT = 1_000_000
SEARCH_QUERY_LIMIT = 300
SEARCH_MAX_TERMS = 10
SEARCH_TERM_MAX = 60
SEARCH_RESULT_LIMIT = 50
DOC_KINDS = ("note", "source", "workstream", "journal", "page")  # what `doc_type` returns: the Type filter of Docs and of the search
SEARCH_SNIPPETS = 2
SEARCH_WINDOW = 160
SEARCH_LEAD = 40
SEARCH_BODY_CAP = 20
SEARCH_OCCURRENCE_CAP = 100
SEARCH_CANDIDATE_CAP = 300
QUERY_TOKEN_RE = re.compile(r'"([^"]*)"|([^\s"]+)')


def parse_query(raw: str) -> list[str]:
    """Normalised search terms: whitespace-separated words or "quoted phrases", all required."""
    if len(raw) > SEARCH_QUERY_LIMIT:
        raise TaskError(HTTPStatus.BAD_REQUEST, f"The search exceeds {SEARCH_QUERY_LIMIT} characters.")
    found = [fold(quoted or bare).strip() for quoted, bare in QUERY_TOKEN_RE.findall(raw)]
    found = [term for term in found if term]
    if len(found) > SEARCH_MAX_TERMS:
        raise TaskError(HTTPStatus.BAD_REQUEST, f"The search accepts {SEARCH_MAX_TERMS} terms at most.")
    if any(len(term) > SEARCH_TERM_MAX for term in found):
        raise TaskError(HTTPStatus.BAD_REQUEST, f"A term exceeds {SEARCH_TERM_MAX} characters.")
    terms: list[str] = []
    for term in found:
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms


class DocEntry:
    """One Markdown file of the brain with its pre-folded fields; ``origin`` (folded index -> source index) is built on demand."""
    __slots__ = ("id", "path", "key", "mtime", "text", "title", "norm_title", "norm_path", "norm_text", "norm_heads", "_origin")

    def __init__(self, doc_id: str, path: str, key: tuple[int, int], text: str) -> None:
        self.id = doc_id
        self.path = path
        self.key = key
        self.mtime = key[0] / 1e9
        self.text = text
        title = ""
        heads: list[str] = []
        fenced = False
        for line in text.splitlines():
            if FENCE_RE.match(line):
                fenced = not fenced
                continue
            match = None if fenced else HEADING_RE.match(line)
            if match and match.group(2):
                heads.append(match.group(2))
                if not title and len(match.group(1)) == 1:
                    title = match.group(2).strip()
        self.title = title or posixpath.splitext(posixpath.basename(doc_id))[0]
        self.norm_title = fold(self.title)
        self.norm_path = fold(doc_id)
        self.norm_text = fold(text)
        self.norm_heads = fold("\n".join(heads))
        self._origin: array | None = None

    @property
    def origin(self) -> array:
        if self._origin is None:
            self._origin = fold_mapped(self.text)[1]
        return self._origin


def _window_pick(starts: list[int], ends: list[int], owners: list[int], length: int, floor: int) -> tuple[int, int] | None:
    """Best ~SEARCH_WINDOW-wide window (folded coordinates) at or after ``floor``: most distinct terms, then most hits, then earliest."""
    best: tuple[tuple[int, int, int], tuple[int, int]] | None = None
    begin = bisect_left(starts, floor)
    for position in range(begin, min(len(starts), begin + SEARCH_CANDIDATE_CAP)):
        first = max(floor, starts[position] - SEARCH_LEAD)
        last = min(length, first + SEARCH_WINDOW)
        inside = [index for index in range(bisect_left(starts, first), bisect_right(starts, last)) if ends[index] <= last]
        key = (len({owners[index] for index in inside}), len(inside), -first)
        if best is None or key > best[0]:
            best = (key, (first, last))
    return best[1] if best else None


def doc_snippets(entry: DocEntry, terms: list[str]) -> list[dict]:
    """Up to two ~160-character excerpts around matches; ``ranges`` are code-point offsets into each snippet text."""
    norm = entry.norm_text
    hits: list[tuple[int, int, int]] = []
    for number, term in enumerate(terms):
        at, count = norm.find(term), 0
        while at != -1 and count < SEARCH_OCCURRENCE_CAP:
            hits.append((at, at + len(term), number))
            count += 1
            at = norm.find(term, at + len(term))
    if not hits:
        return []
    hits.sort()
    starts, ends, owners = [hit[0] for hit in hits], [hit[1] for hit in hits], [hit[2] for hit in hits]
    origin, text = entry.origin, entry.text
    snippets: list[dict] = []
    floor = 0
    while len(snippets) < SEARCH_SNIPPETS:
        window = _window_pick(starts, ends, owners, len(norm), floor)
        if window is None:
            break
        first, last = window
        inside = [index for index in range(bisect_left(starts, first), bisect_right(starts, last)) if ends[index] <= last]
        if not inside:
            break
        if first > 0 and norm[first - 1] != " ":
            cut = norm.find(" ", first, starts[inside[0]])
            first = cut + 1 if cut != -1 else first
        if last < len(norm) and norm[last] != " ":
            cut = norm.rfind(" ", ends[inside[-1]], last)
            last = cut if cut != -1 else last
        floor = last
        raw_first, raw_last = origin[first], origin[last - 1] + 1
        out: list[str] = []
        offsets: list[int] = []
        spaced = True
        for position in range(raw_first, raw_last):
            char = text[position]
            offsets.append(len(out))
            if char.isspace():
                if not spaced:
                    out.append(" ")
                spaced = True
            else:
                out.append(char)
                spaced = False
        offsets.append(len(out))
        if out and out[-1] == " ":
            out.pop()
        body = "".join(out)
        lead = "…" if raw_first > 0 and text[:raw_first].strip() else ""
        tail = "…" if raw_last < len(text) and text[raw_last:].strip() else ""
        ranges: list[list[int]] = []
        for index in inside:
            begin = min(offsets[origin[starts[index]] - raw_first], len(body))
            finish = min(offsets[origin[ends[index] - 1] + 1 - raw_first], len(body))
            if finish <= begin:
                continue
            if ranges and begin <= ranges[-1][1]:
                ranges[-1][1] = max(ranges[-1][1], finish)
            else:
                ranges.append([begin, finish])
        shift = len(lead)
        snippets.append({"text": lead + body + tail, "ranges": [[begin + shift, finish + shift] for begin, finish in ranges]})
        if floor >= len(norm):
            break
    return snippets


class DocsMixin:
    """The documents of a brain, mixed into `Store`: catalogue, recent documents, search and rendering."""

    def _doc_files(self, archived: bool = False):
        """(absolute path, brain-relative id, stat) of every Markdown file: dot-entries, symlinks, oversized files and archived projects are skipped.

        ``archived``: the other way round, only the files of the archived projects (the Archives view, which alone reads them)."""
        stack = [str(self.brain)]
        prefix = len(str(self.brain)) + 1
        while stack:
            folder = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for item in entries:
                if item.name.startswith("."):
                    continue
                try:
                    if item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False):
                        if archived or not self.archived(item.path):
                            stack.append(item.path)
                    elif item.name.lower().endswith(".md") and item.is_file(follow_symlinks=False) and (not archived or self.archived(item.path)):
                        info = item.stat(follow_symlinks=False)
                        if info.st_size <= DOC_SIZE_LIMIT:
                            yield item.path, item.path[prefix:].replace(os.sep, "/"), info
                except OSError:
                    continue

    def docs(self, archived: bool = False) -> list[DocEntry]:
        """Parsed catalogue, cached per file by (path, mtime_ns, size); a changed file is re-read, a vanished one is forgotten.
        ``archived``: the catalogue of the archived projects instead, with its own cache."""
        with self._doc_lock:
            cache = self._archive_cache if archived else self._doc_cache
            fresh: dict[str, DocEntry] = {}
            for path, doc_id, info in self._doc_files(archived):
                key = (info.st_mtime_ns, info.st_size)
                entry = cache.get(doc_id)
                if entry is None or entry.key != key or entry.path != path:
                    try:
                        if not os.path.realpath(path).startswith(str(self.brain) + os.sep):
                            continue
                        with open(path, "rb") as handle:
                            data = handle.read(DOC_SIZE_LIMIT + 1)
                    except OSError:
                        continue
                    if len(data) > DOC_SIZE_LIMIT:
                        continue
                    entry = DocEntry(doc_id, path, key, data.decode("utf-8", "replace").lstrip("﻿"))
                fresh[doc_id] = entry
            if archived:
                self._archive_cache = fresh
            else:
                self._doc_cache = fresh
            return list(fresh.values())

    def _doc_projects(self, archived: bool = False) -> list[tuple[str, str, str]]:
        """(project dir relative to the brain, label, register path), longest directory first.
        ``archived``: the archived projects instead (no Inbox), and each archived root (a client page has no register: its own path)."""
        if archived:
            found = [(path.parent.parent.relative_to(self.brain).as_posix(), action_tool.project_label(path, self.brain), path.relative_to(self.brain).as_posix())
                     for path in self._archived_registers()]
            found += [(root.relative_to(self.brain).as_posix(), self._archive_label(root), root.relative_to(self.brain).as_posix())
                      for root in self.archive_roots()]
        else:
            found = [(info["dir"].relative_to(self.brain).as_posix(), info["label"], info["register"]) for info in self._project_dirs()]
            found.append((INBOX_DIR, INBOX_LABEL, INBOX_REGISTER))
        return sorted(found, key=lambda item: -len(item[0]))

    @staticmethod
    def _doc_project(doc_id: str, projects: list[tuple[str, str, str]]) -> tuple[str, str] | None:
        for folder, label, register in projects:
            if doc_id.startswith(folder + "/"):
                return label, register
        return None

    def recent_docs(self, project: str, limit: int = 20) -> dict:
        """Most recently modified documents of the catalogue (all kinds), for the empty search view."""
        projects = self._doc_projects()
        docs = []
        for entry in sorted(self.docs(), key=lambda item: (-item.mtime, item.id)):
            owner = self._doc_project(entry.id, projects)
            if project == "none" and owner is not None:
                continue
            if project not in {"", "none"} and (owner is None or owner[1] != project):
                continue
            excerpt = note_summary(split_front_matter(entry.text)[1], entry.title)[1]
            docs.append({"id": entry.id, "title": entry.title, "project": owner[0] if owner else None, "register": owner[1] if owner else None,
                         "date": datetime.fromtimestamp(entry.mtime, ZoneInfo("Europe/Paris")).date().isoformat(), "excerpt": excerpt})
            if len(docs) >= limit:
                break
        return {"docs": docs}

    @staticmethod
    def _doc_kind(doc_id: str, owner: tuple[str, str] | None, folders: dict[str, str]) -> str | None:
        """The type of a catalogue file (see `doc_type`); None outside the projects and the Inbox. `folders` maps a register path to its folder."""
        if owner is None:
            return None
        folder = folders[owner[1]]
        return doc_type(doc_id[len(folder) + 1:], posixpath.basename(folder), inbox=owner[1] == INBOX_REGISTER)

    def doc_list(self) -> dict:
        """The Docs view: the working notes (as `notes()` lists them) and the sources, workstreams, journal files and project pages of each project, newest first.

        A file belongs to the project whose folder is the longest prefix of its path. `state/`, `scripts/`, `handoffs/`, the other files of the
        Inbox and the rest of the brain are not listed.
        """
        items = [{**note, "type": "note"} for note in self.notes()["notes"]]
        projects = self._doc_projects()
        folders = {register: folder for folder, _, register in projects}
        for entry in self.docs():
            owner = self._doc_project(entry.id, projects)
            kind = self._doc_kind(entry.id, owner, folders)
            if kind in {None, "note"}:  # the notes come from `notes()`
                continue
            items.append({
                "id": entry.id, "title": entry.title, "project": owner[0], "register": owner[1],
                "date": doc_date(posixpath.basename(entry.id), entry.mtime),
                "modified": datetime.fromtimestamp(entry.mtime, ZoneInfo("Europe/Paris")).isoformat(timespec="seconds"),
                "excerpt": note_summary(split_front_matter(entry.text)[1], entry.title)[1], "size": entry.key[1], "type": kind,
            })
        items.sort(key=lambda item: item["title"].casefold())
        items.sort(key=lambda item: item["date"], reverse=True)
        return {"docs": items}

    def search(self, query: str, project: str, archived: bool = False, kind: str = "") -> dict:
        """The global search of the documents; ``archived``: of the archived projects only (the Archives view), never both.

        ``kind``: only the documents of that type (see `doc_type`), filtered before the best results are kept; ``types`` counts the
        matches of each type whatever ``kind`` is, so the page can say what another type would find.
        """
        if kind and kind not in DOC_KINDS:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid type parameter.")
        terms = parse_query(query)
        empty = {"query": query, "terms": terms, "results": [], "total": 0, "truncated": False, "types": {}}
        if not terms:
            return empty
        projects = self._doc_projects(archived)
        folders = {register: folder for folder, _, register in projects}
        now = datetime.now().timestamp()
        types: dict[str, int] = {}
        matches: list[tuple[float, str, DocEntry, tuple[str, str] | None, str | None]] = []
        for entry in self.docs(archived):
            owner = self._doc_project(entry.id, projects)
            if project == "none" and owner is not None:
                continue
            if project not in {"", "none"} and (owner is None or owner[1] != project):
                continue
            score = 0.0
            for term in terms:
                in_title, in_path = term in entry.norm_title, term in entry.norm_path
                body = entry.norm_text.count(term)
                if not (in_title or in_path or body):
                    break
                score += (10 if in_title else 0) + (5 if in_path else 0)
                score += 3 * min(entry.norm_heads.count(term), 5) + min(body, SEARCH_BODY_CAP)
            else:
                entry_kind = self._doc_kind(entry.id, owner, folders)
                if entry_kind:
                    types[entry_kind] = types.get(entry_kind, 0) + 1
                if kind and entry_kind != kind:
                    continue
                age_days = max(0.0, (now - entry.mtime) / 86400)
                matches.append((round(score + 0.5 / (1 + age_days / 30), 2), entry.id, entry, owner, entry_kind))
        matches.sort(key=lambda item: (-item[0], item[1]))
        results = [{
            "id": entry.id, "title": entry.title, "project": owner[0] if owner else None, "register": owner[1] if owner else None,
            "type": entry_kind, "snippets": doc_snippets(entry, terms), "score": score,
        } for score, _, entry, owner, entry_kind in matches[:SEARCH_RESULT_LIMIT]]
        return {**empty, "results": results, "total": len(matches), "truncated": len(matches) > SEARCH_RESULT_LIMIT, "types": types}

    def render_doc(self, doc_id: object, archived: bool = False) -> dict:
        """A document rendered for the reader; ``archived``: a document of an archived project (read-only, the Archives view), and only those."""
        catalogue = {entry.id: entry for entry in self.docs(archived)}
        entry = catalogue.get(doc_id) if isinstance(doc_id, str) else None
        if entry is None:
            raise TaskError(HTTPStatus.NOT_FOUND, "Document not found.")
        try:
            with open(entry.path, "rb") as handle:
                data = handle.read(DOC_SIZE_LIMIT + 1)
        except OSError:
            raise TaskError(HTTPStatus.NOT_FOUND, "Document not found.") from None
        if len(data) > DOC_SIZE_LIMIT:
            raise TaskError(HTTPStatus.NOT_FOUND, "Document not found.")
        text = data.decode("utf-8", "replace").lstrip("﻿")
        owner = self._doc_project(entry.id, self._doc_projects(archived))
        try:
            self._note_entry(entry.id)
            is_note = not archived  # an archived note is read, never edited
        except TaskError:
            is_note = False
        full = text
        properties, text = split_front_matter(text)
        offset = full[:len(full) - len(text)].count("\n")
        html = front_matter_html(properties) + MARKDOWN.render(text, {"id": entry.id, "ids": set(catalogue), "line_offset": offset})
        return {"id": entry.id, "title": entry.title,
                "project": owner[0] if owner else None, "register": owner[1] if owner else None, "html": html,
                "note": is_note, "deletable": is_note, "version": hashlib.sha256(data).hexdigest()[:16] if is_note else None}
