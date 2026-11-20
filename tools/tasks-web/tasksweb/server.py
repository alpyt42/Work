"""The HTTP server: request handler and the server that serves every brain of Work."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .common import ARCHIVE_VERBS, ASSETS, NOTE_REQUEST_LIMIT, SUBTASKS_ROUTE, SUBTASK_ROUTE, TOOL_LOCK, TaskError, WORK, WRITE_LOCK
from .tools import run_tool, tool_catalog
from .brains import brain_boundary, brain_label, create_brain, discover_brains, validate_new_brain
from .settings import SETTINGS_VALUE_LIMIT, settings_apply, settings_snapshot
from .update import UPDATE_VERSION_RE, UpdateState, update_apply
from .git_sync import GIT_LOCK, GIT_VERSION_RE, git_changes, git_overview, git_save_and_send
from .priorities import read_priorities
from .store import Store

ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2"}


def static_assets() -> dict[str, tuple[str, str]]:
    """What is served outside /api: URL path -> (file below static/, MIME type), read again on every request.

    The page at "/", then each stylesheet and script of static/ and of static/app/ (the page's script, cut into files), and each
    font of static/fonts/, at its own path. Nothing else: no icon, no licence file, no folder, no path built from the URL.
    """
    found = {"/": ("index.html", "text/html; charset=utf-8")}
    for pattern in ("*.css", "*.js", "app/*.js", "fonts/*.woff2"):
        for file in ASSETS.glob(pattern):
            if file.is_file() and not file.name.startswith("."):
                relative = file.relative_to(ASSETS).as_posix()
                found["/" + relative] = (relative, ASSET_TYPES[file.suffix])
    return found


class Handler(BaseHTTPRequestHandler):
    server: TaskServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _headers(self, status: HTTPStatus, mime: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _send(self, status: HTTPStatus, data: bytes, mime: str) -> None:
        self._headers(status, mime, len(data))
        self.wfile.write(data)

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def _store(self) -> Store:
        """The brain selected by the optional `brain=<name>` query parameter (default brain when absent)."""
        values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("brain")
        if values is None:
            return self.server.store
        if len(values) != 1:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid brain parameter.")
        return self.server.store_for(values[0])

    def do_GET(self) -> None:
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Host refused."})
            return
        path = urlsplit(self.path).path
        if path == "/api/brains":
            self._json(HTTPStatus.OK, self.server.brain_list())
            return
        if path in {"/api/git", "/api/git/changes"}:
            self._git_request(path)
            return
        if path == "/api/priorities":
            try:
                name, _ = self.server.git_brain(self._brain_name())
                self._json(HTTPStatus.OK, read_priorities(self.server.work, name))
            except TaskError as error:
                self._json(error.status, {"error": error.message})
            return
        store = self.server.store
        if path.startswith("/api/"):
            try:
                store = self._store()
            except TaskError as error:
                self._json(error.status, {"error": error.message})
                return
        if path == "/api/actions":
            self._json(HTTPStatus.OK, store.snapshot())
            return
        match = re.fullmatch(r"/api/actions/([A-Z]{2,5}-\d{3})/details", path)
        if match:
            try:
                with WRITE_LOCK:
                    result = store.details(match.group(1))
                self._json(HTTPStatus.OK, result)
            except TaskError as error:
                self._json(error.status, {"error": error.message})
            return
        if path == "/api/tools":
            self._json(HTTPStatus.OK, {"tools": tool_catalog()})
            return
        if path == "/api/settings":
            self._json(HTTPStatus.OK, settings_snapshot(self.server.work))
            return
        if path == "/api/update":
            self._json(HTTPStatus.OK, self.server.update.public(cached=True))
            return
        if path == "/api/update/progress":
            self._json(HTTPStatus.OK, self.server.update.progress_public())
            return
        if path in {"/api/notes", "/api/notes/content", "/api/notes/backlinks"}:
            self._notes_request(path, store)
            return
        if path in {"/api/search", "/api/docs/render", "/api/docs/recent", "/api/docs/list"}:
            self._docs_request(path, store)
            return
        if path in {"/api/archives", "/api/archives/project", "/api/archives/plan"}:
            self._archives_request(path, store)
            return
        if path == "/api/undo":
            with WRITE_LOCK:
                self._json(HTTPStatus.OK, store.undo_state())
            return
        assets = static_assets()
        if path not in assets:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
            return
        filename, mime = assets[path]
        data = (ASSETS / filename).read_bytes()
        if path == "/":
            data = data.replace(b"__CSRF_TOKEN__", self.server.token.encode("ascii"))
        self._send(HTTPStatus.OK, data, mime)

    def _notes_request(self, path: str, store: Store) -> None:
        try:
            with WRITE_LOCK:
                if path == "/api/notes":
                    result = store.notes()
                else:
                    values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("id", [])
                    if len(values) != 1:
                        raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid id parameter.")
                    result = store.note_links(values[0]) if path == "/api/notes/backlinks" else store.note_content(values[0])
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not read the notes."})

    def _docs_request(self, path: str, store: Store) -> None:
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)

        def one(name: str, default: str | None = None) -> str:
            values = query.get(name, [] if default is None else [default])
            if len(values) != 1:
                raise TaskError(HTTPStatus.BAD_REQUEST, f"Invalid {name} parameter.")
            return values[0]
        try:
            # `archived=1` (search and reader only): the archived projects instead of the live ones, never both.
            archived = one("archived", "") if path in {"/api/search", "/api/docs/render"} else ""
            if archived not in {"", "1"}:
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid archived parameter.")
            if path == "/api/search":
                result = store.search(one("q", ""), one("project", ""), archived=archived == "1", kind=one("type", ""))
            elif path == "/api/docs/recent":
                result = store.recent_docs(one("project", ""))
            elif path == "/api/docs/list":
                with WRITE_LOCK:  # the notes half is read as `/api/notes` reads it
                    result = store.doc_list()
            else:
                result = store.render_doc(one("id"), archived=archived == "1")
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not read the documents."})

    def _archives_request(self, path: str, store: Store) -> None:
        """`GET /api/archives` (the list), `/api/archives/project?folder=` (one to read), `/api/archives/plan?verb=&folder=` (a dry run)."""
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)

        def one(name: str) -> str:
            values = query.get(name, [])
            if len(values) != 1:
                raise TaskError(HTTPStatus.BAD_REQUEST, f"Invalid {name} parameter.")
            return values[0]
        try:
            with WRITE_LOCK:  # never read halfway through a move
                if path == "/api/archives":
                    result = store.archives()
                elif path == "/api/archives/project":
                    result = store.archive_project(one("folder"))
                else:
                    verb = one("verb")
                    if verb not in {"archive", "unarchive"}:
                        raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid verb parameter.")
                    result = store.archive_plan(verb, one("folder"))
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message, **error.extra})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not read the archives."})

    def _brain_name(self, required: bool = False) -> str | None:
        """The `brain=<name>` query parameter as written (None when absent, unless `required`)."""
        values = parse_qs(urlsplit(self.path).query, keep_blank_values=True).get("brain")
        if values is None:
            if required:
                raise TaskError(HTTPStatus.BAD_REQUEST, "Unknown brain.")
            return None
        if len(values) != 1:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid brain parameter.")
        return values[0]

    def _git_request(self, path: str) -> None:
        """`GET /api/git` (one card per brain, the chosen one first) and `GET /api/git/changes` (what changed in one note)."""
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        try:
            name, brain = self.server.git_brain(self._brain_name())
            if path == "/api/git":
                result = git_overview(self.server.git_brains(), name)
            else:
                values = query.get("path", [])
                if len(values) != 1:
                    raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid path parameter.")
                result = git_changes(name, brain, values[0])
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except OSError:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "Could not read Git."})

    def _write_allowed(self) -> bool:
        """The rules of every write route: this host and origin, the page's token, a JSON body (a refusal is already answered)."""
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin refused."})
        elif self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid local token."})
        elif self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required."})
        else:
            return True
        return False

    def _git_write_request(self, path: str) -> None:
        """`POST /api/git/save` (save the notes of one brain and send them) and `POST /api/git/send` (send what is already saved).

        The brain is named in the address and required; the body carries the `version` of the card the person confirmed.
        """
        if not self._write_allowed():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256:
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or set(payload) != {"version"} or not isinstance(payload["version"], str) or not GIT_VERSION_RE.fullmatch(payload["version"]):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid request.")
            name, brain = self.server.git_brain(self._brain_name(required=True))
            if not GIT_LOCK.acquire(blocking=False):
                raise TaskError(HTTPStatus.CONFLICT, "Another save is already running.")
            try:
                result = git_save_and_send(name, brain, payload["version"], push_only=path == "/api/git/send")
            finally:
                GIT_LOCK.release()
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not run Git."})

    def _write_request(self, kind: str) -> None:
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin refused."})
            return
        if self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid local token."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= (NOTE_REQUEST_LIMIT if kind in {"note_create", "note_update"} else 8192):
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise TaskError(HTTPStatus.BAD_REQUEST, "JSON object required.")
            path = urlsplit(self.path).path
            status = HTTPStatus.OK
            store = self._store()
            with WRITE_LOCK:
                if kind == "create":
                    status, result = HTTPStatus.CREATED, store.create(payload)
                elif kind == "update":
                    match = re.fullmatch(r"/api/actions/([A-Z]{2,5}-\d{3})", path)
                    if not match:
                        raise TaskError(HTTPStatus.NOT_FOUND, "Action not found.")
                    result = store.update(match.group(1), payload)
                elif kind == "add_note":
                    match = re.fullmatch(r"/api/actions/([A-Z]{2,5}-\d{3})/notes", path)
                    if not match:
                        raise TaskError(HTTPStatus.NOT_FOUND, "Action not found.")
                    status, result = HTTPStatus.CREATED, store.add_note(match.group(1), payload)
                elif kind == "archive":
                    result = store.archive_write(ARCHIVE_VERBS[path], payload)
                elif kind == "add_subtask":
                    status, result = HTTPStatus.CREATED, store.add_subtask(SUBTASKS_ROUTE.fullmatch(path).group(1), payload)
                elif kind in {"change_subtask", "remove_subtask"}:
                    match = SUBTASK_ROUTE.fullmatch(path)
                    change = store.change_subtask if kind == "change_subtask" else store.remove_subtask
                    result = change(match.group(1), int(match.group(2)), payload)
                elif kind == "note_create":
                    status, result = HTTPStatus.CREATED, store.create_note(payload)
                elif kind == "note_update":
                    result = store.update_note(payload)
                elif kind == "note_task":
                    result = store.toggle_task(payload)
                elif kind == "note_delete":
                    result = store.delete_note_file(payload)
                elif kind == "undo":
                    result = store.undo(payload)
                elif kind == "delete_action":
                    result = store.delete_action(re.fullmatch(r"/api/actions/([A-Z]{2,5}-\d{3})", path).group(1), payload)
                else:
                    match = re.fullmatch(r"/api/actions/([A-Z]{2,5}-\d{3})/notes/(\d{1,4})", path)
                    if not match:
                        raise TaskError(HTTPStatus.NOT_FOUND, "Note not found.")
                    result = store.delete_note(match.group(1), int(match.group(2)), payload)
                if kind != "undo":
                    result = {**result, "undo": store.undo_state()}
            self._json(status, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message, **error.extra})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})
        except OSError:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The note could not be deleted." if kind == "note_delete" else "The file could not be saved." if kind in {"note_create", "note_update", "note_task"} else "The register could not be saved."})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/shutdown":
            self._shutdown_request()
            return
        if path == "/api/tools/run":
            self._tool_request()
            return
        if path == "/api/brains":
            self._brain_create_request()
            return
        if path in {"/api/update/check", "/api/update/apply"}:
            self._update_request(path)
            return
        if path == "/api/settings":
            self._settings_request()
            return
        if path in {"/api/git/save", "/api/git/send"}:
            self._git_write_request(path)
            return
        if re.fullmatch(r"/api/actions/[A-Z]{2,5}-\d{3}/notes", path):
            self._write_request("add_note")
            return
        if SUBTASKS_ROUTE.fullmatch(path):
            self._write_request("add_subtask")
            return
        if path in ARCHIVE_VERBS:
            self._write_request("archive")
            return
        if path == "/api/undo":
            self._write_request("undo")
            return
        if path == "/api/notes":
            self._write_request("note_create")
            return
        if path != "/api/actions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
            return
        self._write_request("create")

    def _shutdown_request(self) -> None:
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"} or self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Access refused."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json" or self.headers.get("Content-Length") != "2" or self.rfile.read(2) != b"{}":
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid shutdown request."})
            return
        self._json(HTTPStatus.OK, {"stopping": True})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _tool_request(self) -> None:
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin refused."})
            return
        if self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid local token."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256:
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or set(payload) != {"id"} or not isinstance(payload["id"], str):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid tool.")
            brain = self._store().brain
            if not TOOL_LOCK.acquire(blocking=False):
                raise TaskError(HTTPStatus.CONFLICT, "A tool is already running.")
            try:
                result = run_tool(payload["id"], brain)
            finally:
                TOOL_LOCK.release()
            self._json(HTTPStatus.OK, result)
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})

    def _brain_create_request(self) -> None:
        """`POST /api/brains` with {"name": N, "description": D, "scope": S}: create a blank brain with tools/brain/new-brain.py, answer with its entry."""
        if not self._write_allowed():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise TaskError(HTTPStatus.BAD_REQUEST, "JSON object required.")
            name, description, scope = validate_new_brain(payload)
            create_brain(self.server.work, name, description, scope)
            created = next((brain for brain in self.server.brain_list()["brains"] if brain["name"] == name), None)
            if created is None:
                raise TaskError(HTTPStatus.INTERNAL_SERVER_ERROR, f"{name} was created but is not recognised as a brain.")
            self._json(HTTPStatus.CREATED, {"brain": created})
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})

    def _settings_request(self) -> None:
        """`POST /api/settings` with {"key": K, "value": V} or {"key": K, "default": true}: save one setting, answer with the fresh snapshot and a message."""
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin refused."})
            return
        if self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid local token."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get("key"), str) or set(payload) not in ({"key", "value"}, {"key", "default"}):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid settings request.")
            value: str | None = None
            if "default" in payload:
                if payload["default"] is not True:
                    raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid settings request.")
            else:
                value = payload["value"]
                if isinstance(value, list) and all(isinstance(name, str) for name in value):
                    value = ", ".join(value)  # the brains every computer must have
                if not isinstance(value, str) or len(value) > SETTINGS_VALUE_LIMIT:
                    raise TaskError(HTTPStatus.BAD_REQUEST, "Enter a value of 600 characters at most.")
            with WRITE_LOCK:
                message = settings_apply(self.server.work, payload["key"], value)
            self._json(HTTPStatus.OK, {**settings_snapshot(self.server.work), "message": message})
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})

    def _update_request(self, path: str) -> None:
        if not self._host_ok() or self.headers.get("Origin") not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Origin refused."})
            return
        if self.headers.get("X-Tasks-Token") != self.server.token:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid local token."})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required."})
            return
        restart = False
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 256:
                raise TaskError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid update request.")
            if path == "/api/update/check":
                if set(payload) - {"force"} or not isinstance(payload.get("force", False), bool):
                    raise TaskError(HTTPStatus.BAD_REQUEST, "Invalid update request.")
                self._json(HTTPStatus.OK, self.server.update.check(self.server.work, payload.get("force", False)))
                return
            version = payload.get("version")
            if set(payload) != {"version"} or not isinstance(version, str) or not UPDATE_VERSION_RE.fullmatch(version):
                raise TaskError(HTTPStatus.BAD_REQUEST, "A release version such as v1.2.3 is required.")
            status, report = update_apply(self.server.work, version, self.server.update)
            restart = bool(report.get("applied"))
            self._json(status, {**report, "restarting": restart})
        except TaskError as error:
            self._json(error.status, {"error": error.message})
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON."})
        if restart:  # after the response is sent: main() re-executes this command once serve_forever returns
            self.server.restart_requested = True
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_PATCH(self) -> None:
        path = urlsplit(self.path).path
        self._write_request("note_update" if path == "/api/notes" else "note_task" if path == "/api/notes/task" else "change_subtask" if SUBTASK_ROUTE.fullmatch(path) else "update")

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/notes":
            self._write_request("note_delete")
            return
        if SUBTASK_ROUTE.fullmatch(path):
            self._write_request("remove_subtask")
            return
        is_action = re.fullmatch(r"/api/actions/[A-Z]{2,5}-\d{3}", path)
        self._write_request("delete_action" if is_action else "delete_note")


class TaskServer(ThreadingHTTPServer):
    """One server, several brains: `store` is the default brain's Store, the others are built on first use.

    `work` is the Work root whose brains are offered (default: WORK).
    """

    # On Windows SO_REUSEADDR lets a second server take a port already in use: there the bind must fail instead.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple[str, int], store: Store, work: Path | None = None) -> None:
        super().__init__(address, Handler)
        self.work = (work if work is not None else WORK).resolve()
        self.store = store
        self._stores: dict[str, Store] = {}
        self._stores_lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.update = UpdateState()
        self.restart_requested = False

    def _catalog(self) -> tuple[dict[str, Path], str]:
        """(brain name -> folder, name of the default brain), rediscovered on every call.

        The default brain (`--brain`) is the discovered brain with the same folder; when it is none of them it
        is offered first, and it hides a discovered brain that has the same name.
        """
        found = {path.name: path for path in discover_brains(self.work)}
        default = self.store.brain
        for name, path in found.items():
            if path.resolve() == default:
                return found, name
        return {default.name: default, **{name: path for name, path in found.items() if name != default.name}}, default.name

    def brain_list(self) -> dict:
        brains, default = self._catalog()
        return {"brains": [{"name": name, "label": brain_label(name), **brain_boundary(path), "default": name == default}
                           for name, path in brains.items()],
                "default": default}

    def store_for(self, name: str | None) -> Store:
        """The Store of a discovered brain name; None is the default brain. Anything else (a path included) is refused."""
        if name is None:
            return self.store
        brains, default = self._catalog()
        if name == default:
            return self.store
        path = brains.get(name)
        if path is None:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Unknown brain.")
        with self._stores_lock:
            store = self._stores.get(name)
            if store is None or store.brain != path.resolve():
                try:
                    store = self._stores[name] = Store(path)
                except ValueError:
                    raise TaskError(HTTPStatus.NOT_FOUND, "This brain has no projects folder.") from None
            return store

    def git_brains(self) -> dict[str, Path]:
        """The brains the Sync view lists: the discovered ones, the default brain first. Never Work itself."""
        return self._catalog()[0]

    def git_brain(self, name: str | None) -> tuple[str, Path]:
        """(name, folder) of a discovered brain; None is the default brain. Anything else (a path included) is refused."""
        brains, default = self._catalog()
        name = default if name is None else name
        path = brains.get(name)
        if path is None:
            raise TaskError(HTTPStatus.BAD_REQUEST, "Unknown brain.")
        return name, path.resolve()
