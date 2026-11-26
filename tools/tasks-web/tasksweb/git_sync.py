"""Git: save and send the changes of a brain (the Sync view).

The Sync view works on the brains found in Work, never on Work itself and never on a path or a repository
chosen by the page. Listing never touches the network. Saving is one confirmed `git add -A`, `git commit` and
`git push` of one brain, with every Git hook running, no terminal to ask anything on and a time limit. The only other
network calls are a throttled `git fetch` (to learn whether the online copy is ahead) and a fast-forward-only pull
(`git merge --ff-only` after a fetch): never a merge commit, a rebase or a force.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import os
import posixpath
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import INBOX_DIR, INBOX_LABEL, TaskError, action_tool, preflight_push
from .markdown import FENCE_RE, HEADING_RE, split_front_matter
from .brains import brain_label

GIT_READ_TIMEOUT = 10
GIT_ADD_TIMEOUT = 60
GIT_COMMIT_TIMEOUT = 180
GIT_PUSH_TIMEOUT = 120
GIT_FETCH_TIMEOUT = 20
GIT_PULL_TIMEOUT = 60
GIT_FETCH_EVERY = 300  # seconds between two real fetches of one brain, unless forced
GIT_CHANGE_LIMIT = 200  # changed notes listed for one brain (the count stays exact)
GIT_COMPARE_LIMIT = 300_000  # bytes read on each side of a comparison
GIT_COMPARE_LINES = 3000  # lines shown by "See changes"
GIT_CONTEXT_LINES = 2
GIT_TITLE_READ = 16384
GIT_TITLE_DELETED_LIMIT = 50  # deleted notes whose committed title is read (one Git call each)
GIT_RENAME_SCAN_LIMIT = 300
GIT_DETAILS_LIMIT = 20_000
GIT_BODY_LIMIT = 50
GIT_TEXT_PEEK = 8192
GIT_SENSITIVE = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "*.kdbx", "credentials*", "*secret*", "*.token")
GIT_STRIPPED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE")
# Variables that could make SSH or Git ask a question somewhere else than on a terminal (GIT_SSH_COMMAND and GIT_SSH are never set
# here, and never removed: the pre-push check refuses them).
GIT_NO_PROMPT_ENV = ("SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "GIT_ASKPASS", "DISPLAY")
GIT_LOCK = threading.Lock()
GIT_FETCH_STATE: dict[str, dict] = {}  # brain folder -> {"mono": monotonic time of the last attempt, "at": ISO time, "error": short reason or ""}
GIT_VERSION_RE = re.compile(r"^[0-9a-f]{32}$")
GIT_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GIT_BRANCH_REF_RE = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*$")
GIT_UNAVAILABLE = {
    "not_set_up": "Saving is unavailable here (this brain is not set up for saving): ask your agent to set it up.",
    "no_online_copy": "Saving is unavailable here (this brain has no online copy yet): ask your agent to connect it.",
    "detached": "Saving is unavailable here (this brain is not on its working branch): ask your agent to fix it.",
    "in_progress": "Saving is unavailable here (a merge or a rebase is in progress): ask your agent to finish it.",
    "unreadable": "Saving is unavailable here (Git could not read this brain): ask your agent to check it.",
}
GIT_MESSAGES = {
    "clean": "Everything is saved and sent.",
    "unsent": "Saved on this computer, not sent yet.",
    "behind": "This brain was changed on another computer. Ask your agent to bring those changes here before saving.",
    "pullable": "{count} on another computer, not here yet.",
    "pull_first": "This brain was changed on another computer. Pull those changes here before saving.",
    "pullable_local": " Your unsaved notes stay as they are.",
}
GIT_CHANGED_NOTES = "{count} {notes} changed since the last save."
GIT_STALE = "These notes changed since you last looked. Check the list and try again."


def is_sensitive(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in GIT_SENSITIVE)


def git_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in GIT_STRIPPED_ENV}


def git_program(windows: bool | None = None) -> str:
    """Git on PATH, else its usual place: /usr/bin/git, or on Windows the folders of Git for Windows."""
    found = shutil.which("git")
    if found:
        return found
    if not (os.name == "nt" if windows is None else windows):
        return "/usr/bin/git"
    roots = [os.environ.get(name) for name in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    roots.append(str(Path(os.environ["LOCALAPPDATA"]) / "Programs") if os.environ.get("LOCALAPPDATA") else None)
    for root in filter(None, roots):
        for relative in ("Git/cmd/git.exe", "Git/bin/git.exe"):
            if (Path(root) / relative).is_file():
                return str(Path(root) / relative)
    return "git.exe"  # not found: the call fails with OSError, said as "Git was not found on this machine."


def kill_tree(process: subprocess.Popen) -> None:
    """Kill a command and every process it started: its process group on macOS and Linux, its tree on Windows."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=10, check=False,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
        process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()


def run_git(repo: Path, *args: str) -> bytes:
    """Read-only Git call: fixed argv, no shell, no network, no prompt, no optional lock."""
    environment = git_environment()
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_PAGER": "cat"})
    try:
        result = subprocess.run(
            [git_program(), "--no-pager", "-c", "core.quotepath=false", "-c", "color.ui=false", *args],
            cwd=repo, capture_output=True, timeout=GIT_READ_TIMEOUT, env=environment, check=False, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise TaskError(HTTPStatus.BAD_GATEWAY, "Git did not answer within 10 seconds.") from None
    except OSError:
        raise TaskError(HTTPStatus.BAD_GATEWAY, "Git was not found on this machine.") from None
    if result.returncode != 0:
        raise TaskError(HTTPStatus.BAD_GATEWAY, "Git returned an error for this repository.")
    return result.stdout


def run_git_write(repo: Path, args: list[str], timeout: int) -> tuple[int, str]:
    """A Git call that may change the brain or reach the online copy.

    stdin is closed, nothing can prompt (`GIT_TERMINAL_PROMPT=0`, no askpass) and the command runs in its own session,
    so it has no controlling terminal and SSH can never wait for a passphrase. The hooks run as they do from a terminal.
    Returns (exit status, output of both streams); 124 after the time limit (the whole process group is killed), 127
    when Git cannot start.
    """
    environment = git_environment()
    for name in GIT_NO_PROMPT_ENV:
        environment.pop(name, None)
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_EDITOR": "true", "GIT_PAGER": "cat",
                        "LC_MESSAGES": "C", "LANGUAGE": "C"})
    try:
        # Its own session (no controlling terminal) on macOS and Linux; on Windows its own process group, killed as a tree.
        detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(
            [git_program(), "--no-pager", "-c", "core.quotepath=false", "-c", "color.ui=false", *args], cwd=repo,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment, **detach,
        )
    except OSError:
        return 127, ""
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            output = b""
        return 124, output.decode("utf-8", "replace")
    return process.returncode, (output or b"").decode("utf-8", "replace")


def change_word(item: dict) -> str:
    """The change in words: New, Edited, Deleted or Renamed."""
    if item["untracked"]:
        return "New"
    if item["index"] == "D" or item["worktree"] == "D":
        return "Deleted"
    if item["index"] == "R":
        return "Renamed"
    if item["index"] in ("A", "C"):
        return "New"
    return "Edited"


def parse_git_status(raw: bytes) -> tuple[dict, list[dict]]:
    tokens = raw.decode("utf-8", "replace").split("\0")
    head: dict[str, str] = {}
    files: list[dict] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        kind = token[0]
        orig = None
        blob = ""
        if token.startswith("# "):
            key, _, value = token[2:].partition(" ")
            head[key] = value
            continue
        if kind == "1" and len(token.split(" ", 8)) == 9:
            parts = token.split(" ", 8)
            code, path, blob = parts[1], parts[8], parts[6]
        elif kind == "2" and len(token.split(" ", 9)) == 10:
            parts = token.split(" ", 9)
            code, path, blob = parts[1], parts[9], parts[6]
            orig = tokens[index] if index < len(tokens) else None
            index += 1
        elif kind == "u" and len(token.split(" ", 10)) == 11:
            parts = token.split(" ", 10)
            code, path = "UU", parts[10]
        elif kind == "?":
            code, path = "?", token[2:]
        else:
            continue
        if code == "?":
            side_index, side_tree = ".", "?"
        elif code == "UU":
            side_index, side_tree = "U", "U"
        else:
            side_index = "M" if code[0] == "T" else code[0]
            side_tree = "." if code[1] == "." else "D" if code[1] == "D" else "M"
        item = {
            "path": path, "orig_path": orig, "index": side_index, "worktree": side_tree, "untracked": code == "?",
            "unmerged": code == "UU", "head_oid": blob, "sensitive": is_sensitive(path),
        }
        item["change"] = change_word(item)
        files.append(item)
    files.sort(key=lambda entry: entry["path"])
    return head, files


def read_worktree(brain: Path, relative: str, limit: int) -> bytes | None:
    """Up to limit + 1 bytes of a regular file of the brain (a symbolic link is never followed); None when it cannot be read."""
    full = brain / relative
    try:
        if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(brain.resolve()):
            return None
        with full.open("rb") as handle:
            return handle.read(limit + 1)
    except OSError:
        return None


def git_blob(brain: Path, relative: str, limit: int) -> tuple[bytes | None, bool]:
    """(content of a file as last saved, whether it is larger than `limit`); content is None when it is missing or too large."""
    try:
        size = int(run_git(brain, "cat-file", "-s", f"HEAD:{relative}").strip())
        if size > limit:
            return None, True
        return run_git(brain, "cat-file", "blob", f"HEAD:{relative}"), False
    except (TaskError, ValueError):
        return None, False


def blob_ids(data: bytes, algorithm: str) -> list[str]:
    """The object ids Git may give a file's bytes: as they are, then with CRLF stored as LF.

    Brains check text in with `text=auto eol=lf`: a note an editor saved with CRLF (on Windows) is committed with LF, so
    its blob id is the one of the LF form.
    """
    forms = [data]
    if b"\r\n" in data and b"\0" not in data[:GIT_TEXT_PEEK]:
        forms.append(data.replace(b"\r\n", b"\n"))
    return [hashlib.new(algorithm, b"blob %d\0" % len(form) + form).hexdigest() for form in forms]


def pair_renames(brain: Path, files: list[dict]) -> list[dict]:
    """A note moved without a change appears as a deletion and a new file: show it as one renamed note."""
    gone: dict[str, list[dict]] = {}
    for item in files:
        if item["worktree"] == "D" and item["index"] == "." and item["head_oid"]:
            gone.setdefault(item["head_oid"], []).append(item)
    fresh = [item for item in files if item["untracked"]]
    if not gone or not fresh:
        return files
    algorithm = "sha256" if len(next(iter(gone))) == 64 else "sha1"
    paired: set[int] = set()
    for item in fresh[:GIT_RENAME_SCAN_LIMIT]:
        data = read_worktree(brain, item["path"], GIT_COMPARE_LIMIT)
        if data is None or len(data) > GIT_COMPARE_LIMIT:
            continue
        candidates = next((gone[oid] for oid in blob_ids(data, algorithm) if gone.get(oid)), None)
        if candidates:
            old = candidates.pop(0)
            item.update(orig_path=old["path"], untracked=False, change="Renamed", sensitive=item["sensitive"] or old["sensitive"])
            paired.add(id(old))
    return [item for item in files if id(item) not in paired]


def git_title(text: str, fallback: str) -> str:
    """First level-1 Markdown heading outside code, else `fallback`."""
    fenced = False
    for line in split_front_matter(text)[1].splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING_RE.match(line)
        if match and len(match.group(1)) == 1 and match.group(2).strip():
            return " ".join(match.group(2).split())[:120]
    return fallback


def git_project(brain: Path, relative: str) -> str:
    """The project a changed file belongs to (the label of its register, `client / mission` or the project folder), else ''."""
    parts = relative.split("/")
    if parts[0] == INBOX_DIR and len(parts) > 1:
        return INBOX_LABEL
    if parts[0] != "projects":
        return ""
    for depth in range(len(parts) - 1, 1, -1):
        register = brain.joinpath(*parts[:depth], "state/actions.md")
        if register.is_file() and not register.is_symlink():
            return action_tool.project_label(register, brain)
    # No register (a client page, or a project deleted with its register): the same rule, read from the path.
    inner = list(action_tool.live_parts(tuple(parts[1:-1])))  # an archived project or client reads like a live one
    if len(inner) >= 4 and inner[0] == "clients" and inner[2] == "missions":
        return f"{inner[1]} / {inner[3]}"
    return inner[1] if len(inner) >= 2 else ""


def describe_changes(brain: Path, files: list[dict]) -> list[dict]:
    """The changed notes in human terms: title, project and the change in a word (no hash, no line counts)."""
    items = []
    deleted_reads = 0
    for item in files[:GIT_CHANGE_LIMIT]:
        path = item["path"]
        base = posixpath.basename(path)
        title = posixpath.splitext(base)[0] or base
        if not item["sensitive"] and path.lower().endswith(".md"):
            data = None
            if item["change"] == "Deleted":
                if deleted_reads < GIT_TITLE_DELETED_LIMIT:
                    deleted_reads += 1
                    data = git_blob(brain, path, GIT_TITLE_READ * 4)[0]
            else:
                data = read_worktree(brain, path, GIT_TITLE_READ)
            if data:
                title = git_title(data[:GIT_TITLE_READ].decode("utf-8", "replace"), title)
        items.append({"path": path, "title": title, "project": git_project(brain, path), "change": item["change"],
                      "from": item["orig_path"] or "", "hidden": item["sensitive"]})
    return items


def git_directory(brain: Path) -> Path | None:
    try:
        return Path(run_git(brain, "rev-parse", "--absolute-git-dir").decode("utf-8", "replace").strip())
    except TaskError:
        return None


def git_operation_in_progress(brain: Path) -> bool:
    folder = git_directory(brain)
    return folder is not None and any((folder / name).exists() for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"))


def git_push_target(brain: Path, branch: str) -> tuple[str, str] | None:
    """(remote name, branch ref on the remote) the current branch is set up to push to, from its upstream configuration."""
    try:
        text = run_git(brain, "config", "--get-regexp", rf"^branch\.{re.escape(branch)}\.(remote|merge)$").decode("utf-8", "replace")
    except TaskError:
        return None
    values = {}
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        values[key.rsplit(".", 1)[-1]] = value.strip()
    remote, ref = values.get("remote", ""), values.get("merge", "")
    return (remote, ref) if GIT_REMOTE_RE.fullmatch(remote) and GIT_BRANCH_REF_RE.fullmatch(ref) else None


def git_online_copy(brain: Path, remote: str | None) -> str:
    """The push URL of the remote the brain sends to (its upstream's, else `origin`), credentials hidden; '' when it has none.

    Only a local read of the configuration: no network. The URL is shown to the person, so it goes through the same rule as the
    push checks (HTTPS user-info becomes `https://***@host`; SSH user-info is removed).
    """
    try:
        text = run_git(brain, "remote", "get-url", "--push", remote or "origin").decode("utf-8", "replace")
    except TaskError:
        return ""
    url = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return "".join(char for char in preflight_push.redact(url) if char.isprintable())[:300]


WEB_URL_SCHEMES = ("http", "https", "ssh", "ssh+git", "git+ssh")
WEB_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")  # a dotted name or an IPv4 address
# One path segment: plain URL characters or a %XX escape that is not a control character, a slash or a backslash.
WEB_SEGMENT_RE = re.compile(r"^(?:[A-Za-z0-9._~+-]|%(?!0[0-9a-fA-F]|1[0-9a-fA-F]|7[fF]|2[fF]|5[cC])[0-9a-fA-F]{2})+$")
WEB_AUTHORITY_URL_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)(/[^?#]*)?$")
WEB_SCP_URL_RE = re.compile(r"^(?:[^@/:\s]+@)?([^/:\s@]+):([^/\s].*)$")


def git_web_url(url: str) -> str | None:
    """The web page of a repository, from its (already redacted) Git URL; None when there is no safe way to say it.

    `git@host:owner/repo.git`, `ssh://[user@]host[:port]/owner/repo.git` (user and port dropped, the port of SSH is not the one of the
    web) and `http(s)://[credentials@]host[:port]/owner/repo[.git]` give `https://host/owner/repo` (`http` stays `http`). Local paths, `file://`,
    `git://` and every other form give None. The result is built from checked parts only (a dotted host name, plain path segments),
    so it is always an `http(s)` address, never another scheme and never a query or a fragment.
    """
    text = url.strip() if isinstance(url, str) else ""
    if not text or len(text) > 300 or "\\" in text or any(ord(char) <= 32 or ord(char) == 127 for char in text):
        return None
    authority = WEB_AUTHORITY_URL_RE.match(text)
    if authority:
        scheme, location, path = authority.group(1).lower(), authority.group(2), authority.group(3) or ""
        if scheme not in WEB_URL_SCHEMES:
            return None
        host, _, port = location.rsplit("@", 1)[-1].partition(":")
        if port and (not port.isdigit() or not 0 < int(port) <= 65535):
            return None
        web_scheme = "http" if scheme == "http" else "https"
        web_port = port if scheme in ("http", "https") else ""
        path = path[1:]
    else:
        scp = WEB_SCP_URL_RE.match(text)
        if scp is None:
            return None
        (host, path), web_scheme, web_port = scp.groups(), "https", ""
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = path.split("/")
    if not WEB_HOST_RE.fullmatch(host) or len(segments) < 2 or any(segment in ("", ".", "..") or not WEB_SEGMENT_RE.fullmatch(segment) for segment in segments):
        return None
    return f"{web_scheme}://{host.lower()}{':' + web_port if web_port else ''}/{'/'.join(segments)}"


def git_last_saved(brain: Path) -> str | None:
    try:
        stamp = run_git(brain, "log", "-1", "--format=%ct").decode().strip()
    except TaskError:
        return None
    return datetime.fromtimestamp(int(stamp), ZoneInfo("Europe/Paris")).isoformat(timespec="seconds") if stamp.isdigit() else None


def plural_changes(count: int) -> str:
    return f"{count} change is" if count == 1 else f"{count} changes are"


def git_fetch_info(brain: Path) -> dict:
    """When the online copy was last checked from this page and what went wrong, from memory (no network)."""
    state = GIT_FETCH_STATE.get(str(brain))
    return {"fetched_at": state["at"] if state else None, "fetch_error": state["error"] if state else ""}


def git_inspect(name: str, brain: Path) -> tuple[dict, tuple[str, str] | None, list[dict]]:
    """The card of a brain: where things stand in one sentence, the changed notes, and what the button does.

    Also returns the (remote, branch ref) a push goes to and the raw changed files; nothing here uses the network (the
    online copy is known as of the last fetch only).
    """
    card: dict = {"name": name, "label": brain_label(name), "state": "unavailable", "message": "", "pending": False, "action": None,
                  "count": 0, "unsent": 0, "changes": [], "more": 0, "last_saved": None, "version": "", "url": "", "web_url": None,
                  "behind": 0, "pullable": False, **git_fetch_info(brain)}

    def unavailable(reason: str) -> tuple[dict, None, list[dict]]:
        return {**card, "message": GIT_UNAVAILABLE[reason]}, None, []

    if not (brain / ".git").exists():
        return unavailable("not_set_up")
    try:
        raw = run_git(brain, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all")
    except TaskError:
        return unavailable("unreadable")
    head, files = parse_git_status(raw)
    files = pair_renames(brain, files)
    changes = describe_changes(brain, files)
    digest = hashlib.sha256(raw)
    for item in files:
        try:
            info = (brain / item["path"]).lstat()
            digest.update(f"{item['path']}\0{info.st_size}\0{info.st_mtime_ns}\0".encode())
        except OSError:
            pass
    card.update(count=len(files), changes=changes, more=max(0, len(files) - len(changes)), last_saved=git_last_saved(brain), version=digest.hexdigest()[:32])
    branch = head.get("branch.head", "")
    target = git_push_target(brain, branch) if branch and branch != "(detached)" else None
    card["url"] = git_online_copy(brain, target[0] if target else None)
    card["web_url"] = git_web_url(card["url"])
    counts = re.fullmatch(r"\+(\d+) -(\d+)", head.get("branch.ab", ""))
    if any(item["unmerged"] for item in files) or git_operation_in_progress(brain):
        card["message"] = GIT_UNAVAILABLE["in_progress"]
        return card, None, files
    if branch == "(detached)" or not branch:
        card["message"] = GIT_UNAVAILABLE["detached"]
        return card, None, files
    if target is None or not head.get("branch.upstream") or counts is None:
        card["message"] = GIT_UNAVAILABLE["no_online_copy"]
        return card, None, files
    ahead, behind = int(counts.group(1)), int(counts.group(2))
    card["unsent"] = ahead
    if behind:
        card.update(state="behind", behind=behind, message=GIT_MESSAGES["behind"])
        if not ahead:  # nothing of ours to merge: the online copy can simply be brought here
            card.update(pullable=True, action="pull", message=GIT_MESSAGES["pullable"].format(count=plural_changes(behind)) + (GIT_MESSAGES["pullable_local"] if files else ""))
    elif files:
        card.update(state="changes", action="save", message=GIT_CHANGED_NOTES.format(count=len(files), notes="note" if len(files) == 1 else "notes"))
    elif ahead:
        card.update(state="unsent", action="send", message=GIT_MESSAGES["unsent"])
    else:
        card.update(state="clean", message=GIT_MESSAGES["clean"])
    card["pending"] = card["state"] in ("changes", "unsent") or (card["state"] == "behind" and bool(files or ahead))
    return card, target, files


def git_card(name: str, brain: Path) -> dict:
    return git_inspect(name, brain)[0]


def git_overview(brains: dict[str, Path], current: str) -> dict:
    """One card per brain of the Work, the current brain first (never Work itself)."""
    names = [current, *(name for name in brains if name != current)]
    return {"brains": [git_card(name, brains[name].resolve()) for name in names if name in brains]}


def to_lines(data: bytes) -> list[str]:
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:2000] for line in lines]


def git_changes(name: str, brain: Path, relative: str) -> dict:
    """"See changes" for one changed note: what it was at the last save against what it is now, with the unchanged part collapsed."""
    _, _, files = git_inspect(name, brain)
    item = next((entry for entry in files if entry["path"] == relative), None)
    if item is None:
        raise TaskError(HTTPStatus.NOT_FOUND, "This note has no change to save.")
    described = describe_changes(brain, [item])[0]
    result = {"path": relative, "title": described["title"], "project": described["project"], "change": item["change"],
              "hidden": False, "binary": False, "too_large": False, "unchanged": False, "truncated": False, "blocks": []}
    if item["sensitive"]:
        return {**result, "hidden": True}
    old, new = b"", b""
    if item["change"] != "New":
        old, too_large = git_blob(brain, item["orig_path"] or relative, GIT_COMPARE_LIMIT)
        if too_large:
            return {**result, "too_large": True}
        old = old or b""
    if item["change"] != "Deleted":
        new = read_worktree(brain, relative, GIT_COMPARE_LIMIT)
        if new is None:
            raise TaskError(HTTPStatus.NOT_FOUND, "This note cannot be shown.")
        if len(new) > GIT_COMPARE_LIMIT:
            return {**result, "too_large": True}
    if b"\0" in old[:GIT_TEXT_PEEK] or b"\0" in new[:GIT_TEXT_PEEK]:
        return {**result, "binary": True}
    before, after = to_lines(old), to_lines(new)
    if len(before) > 5000 or len(after) > 5000:
        return {**result, "too_large": True}
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    blocks: list[list] = []
    covered = 0  # lines of `before` accounted for so far (an unchanged line counts the same on both sides)
    for group in matcher.get_grouped_opcodes(GIT_CONTEXT_LINES):
        if group[0][1] > covered:
            blocks.append(["gap", group[0][1] - covered])
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                blocks.extend(["ctx", line] for line in before[i1:i2])
            else:
                if tag in ("delete", "replace"):
                    blocks.extend(["del", line] for line in before[i1:i2])
                if tag in ("insert", "replace"):
                    blocks.extend(["add", line] for line in after[j1:j2])
        covered = group[-1][2]
    if blocks and covered < len(before):
        blocks.append(["gap", len(before) - covered])
    shown = 0
    for position, block in enumerate(blocks):
        if block[0] != "gap":
            shown += 1
            if shown > GIT_COMPARE_LINES:
                return {**result, "blocks": blocks[:position], "truncated": True}
    return {**result, "blocks": blocks, "unchanged": not blocks}


# What a refusal looks like in plain words. The first group reads the output of the brain's pre-commit hook (and of commit-msg),
# the second one the output of a push (Git itself and the pre-push identity checks).
GIT_NOISE = re.compile(r"^(hint:|Commit refused:?( fix the problems|$)|Push refused: fix the ERROR|Summary:|files +:|md links|wikilinks|dead \(|cross-brain|unverified|Action check:|Total (sweep|archive)|Known-name scan|Client-name scan|\(dry run)")


def git_note_name(path: str, titles: dict[str, str]) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0] or path
    return f"“{titles.get(path) or stem}”"


def git_first_line(output: str) -> str:
    lines = [line.strip() for line in output.replace("\r", "").splitlines()]
    lines = [line for line in lines if line and "--no-verify" not in line and not GIT_NOISE.match(line) and re.search(r"\w", line)]
    preferred = next((line for line in lines if re.match(r"(error:|fatal:|ERROR\b|⛔)", line)), lines[0] if lines else "")
    return re.sub(r"^(error:|fatal:|ERROR:?|⛔|-)\s*", "", preferred).strip().rstrip(".")[:200]


def git_commit_reason(output: str, code: int, titles: dict[str, str]) -> str:
    """Why the commit was refused, in a few plain words: the hooks of the brain, recognised one by one, else their first useful line."""
    text = output.replace("\r", "")
    if code == 124:
        return "the checks did not finish in time"
    if code == 127:
        return "Git could not be started"
    if "index.lock" in text:
        return "another program is using this brain right now: try again in a moment"
    secret = re.search(r"Possible secrets in the index.*?\n\s*- (.+?)(?::\d+)?: (.+)", text, re.DOTALL)
    if secret:
        label = secret.group(2).strip()
        if label.startswith("credentials file"):
            return f"{git_note_name(secret.group(1), titles)} looks like a file of credentials"
        return f"{git_note_name(secret.group(1), titles)} seems to contain a password, a key or a token"
    link = re.search(r"DEAD (?:MD LINK|WIKILINK) [(\[]+(.+?)[)\]]+ — \d+×\s*\n\s+(\S.*)", text)
    if link:
        return f"a link in {git_note_name(link.group(2).strip(), titles)} points to a note that does not exist ({link.group(1)})"
    cross = re.search(r"CROSS-BRAIN LINK [(\[]+(.+?)[)\]]+ — \d+×.*\n\s+(\S.*)", text)
    if cross:
        return f"a link in {git_note_name(cross.group(2).strip(), titles)} points into another brain"
    other = re.search(r"^Blocked .*? in (.+?): (.+)$", text, re.MULTILINE)
    if other:
        return f"{git_note_name(other.group(1), titles)} mentions a name that belongs to another brain ({other.group(2).strip()})"
    misfiled = re.search(r": sweep ([A-Z]{2,5}-\d{3}) .*? → (.+)$", text, re.MULTILINE)
    if misfiled:
        return f"action {misfiled.group(1)} is not under the section of its status ({misfiled.group(2).strip().capitalize()})"
    problem = re.search(r"^ERROR (.+?): (.+)$", text, re.MULTILINE)
    if problem:
        path = problem.group(1).split(":", 1)[0]
        detail = problem.group(2)
        if "malformed action line" in detail:
            return f"an action line in {git_note_name(path, titles)} is not written the way registers expect"
        if "already present" in detail:
            return f"an action number is used twice in {git_note_name(path, titles)}"
        return f"an action register has a problem ({problem.group(1)}: {detail})"
    if re.search(r"nothing (added )?to commit|no changes added", text):
        return "there was nothing new to save"
    return git_first_line(text) or "a check of the brain refused it"


def git_push_reason(output: str, code: int) -> str:
    """Why the push failed, in a few plain words."""
    text = output.replace("\r", "")
    if code == 124:
        return "the online copy did not answer in time"
    if code == 127:
        return "Git could not be started"
    if re.search(r"GIT_SSH(_COMMAND)? is set", text):
        return "this computer overrides the connection settings of Git (GIT_SSH_COMMAND): ask your agent to check it"
    if re.search(r"ERROR: user\.(email|name)|does not match the \"email\" pattern|no effective user\.email", text):
        return "the Git identity of this computer does not match this brain: ask your agent to check it"
    if re.search(r"does not match the \"remote\" pattern|no push URL to compare", text):
        return "the online copy is not the one this brain is declared to use: ask your agent to check it"
    ssh = re.search(r"SSH authentication to \S+ failed: (.+)", text)
    if ssh or re.search(r"Permission denied \(publickey", text):
        reason = ssh.group(1) if ssh else "permission denied"
        if "host key" in reason:
            return "the identity of the online copy could not be verified: ask your agent to check it"
        if "permission denied" in reason:
            return "the online copy refused the connection (the SSH key is locked or not accepted)"
        return "the online copy could not be reached (check the network)"
    if re.search(r"remote is ahead|history diverged|the remote moved|non-fast-forward|\[rejected\]|fetch first|remote tip is unknown", text):
        return "the online copy has newer changes: ask your agent to bring them here before sending"
    if re.search(r"Could not resolve host|Network is unreachable|Connection (timed out|refused|reset)|unable to access|Could not read from remote", text):
        return "the online copy could not be reached (check the network)"
    return git_first_line(text) or "the online copy did not accept the changes"


def git_index_file(brain: Path) -> Path | None:
    try:
        location = run_git(brain, "rev-parse", "--git-path", "index").decode("utf-8", "replace").strip()
    except TaskError:
        return None
    return brain / location if location else None


def git_clear_stale_lock(index: Path | None, since: float) -> None:
    """A Git command that was killed may leave its index.lock behind: remove the one made since `since` (never an older one)."""
    if index is None:
        return
    lock = index.with_name(index.name + ".lock")
    try:
        if lock.is_file() and lock.stat().st_mtime >= since - 1:
            lock.unlink()
    except OSError:
        pass


def git_restore_index(index: Path | None, backup: bytes | None) -> bool:
    """Put the index back as it was before `git add -A`, the way Git itself replaces it (through index.lock). False when it could not."""
    if index is None:
        return False
    lock = index.with_name(index.name + ".lock")
    try:
        handle = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError:
        return False
    try:
        with os.fdopen(handle, "wb") as stream:
            if backup is not None:
                stream.write(backup)
                stream.flush()
                os.fsync(stream.fileno())
        if backup is None:
            lock.unlink()
            index.unlink(missing_ok=True)
        else:
            os.replace(lock, index)
        return True
    except OSError:
        lock.unlink(missing_ok=True)
        return False


def git_head(brain: Path) -> str:
    try:
        return run_git(brain, "rev-parse", "--verify", "-q", "HEAD").decode().strip()
    except TaskError:
        return ""


def git_commit_message(card: dict) -> tuple[str, str]:
    """Conventional Commits subject accepted by the commit-msg hook (no scope, no AI attribution) and a short body listing the files."""
    count = card["count"]
    subject = f"docs: save {count} {'note' if count == 1 else 'notes'} from tasks-web"
    lines = []
    for item in card["changes"][:GIT_BODY_LIMIT]:
        where = f"{item['from']} -> {item['path']}" if item["from"] else item["path"]
        lines.append(f"- {item['change'].lower()}: {where}")
    if count > len(lines):
        lines.append(f"- and {count - len(lines)} more")
    return subject, "\n".join(lines)


def git_outcome(ok: bool, stage: str, message: str, details: str, brain: dict, saved: bool = False) -> dict:
    return {"ok": ok, "stage": stage, "saved": saved, "message": message, "details": details.strip()[:GIT_DETAILS_LIMIT], "brain": brain}


def git_save_and_send(name: str, brain: Path, version: str, push_only: bool) -> dict:
    """Save (`git add -A`, `git commit`) and send (`git push`) one brain; or only send what is already saved.

    The brain's hooks all run. Refuses when the brain is not in a safe state, when the notes changed since the page
    listed them (`version`) or when there is nothing to do. A refused commit puts the index back as it was.
    """
    card, target, _ = git_inspect(name, brain)
    if card["state"] in ("unavailable", "behind") or target is None:
        raise TaskError(HTTPStatus.CONFLICT, GIT_MESSAGES["pull_first"] if card["pullable"] else card["message"])
    if card["version"] != version:
        raise TaskError(HTTPStatus.CONFLICT, GIT_STALE)
    if push_only and not card["unsent"]:
        raise TaskError(HTTPStatus.CONFLICT, "Nothing is waiting to be sent.")
    if not push_only and card["state"] == "clean":
        raise TaskError(HTTPStatus.CONFLICT, "Everything is already saved and sent.")
    details = ""
    saved = False
    if not push_only and card["count"]:
        head = git_head(brain)
        index = git_index_file(brain)
        backup = index.read_bytes() if index is not None and index.is_file() else None
        titles = {item["path"]: item["title"] for item in card["changes"]}
        started = datetime.now().timestamp()
        code, output = run_git_write(brain, ["add", "-A"], GIT_ADD_TIMEOUT)
        details = output
        if code == 0:
            subject, body = git_commit_message(card)
            code, output = run_git_write(brain, ["commit", "-m", subject, "-m", body], GIT_COMMIT_TIMEOUT)
            details = f"{details}\n{output}"
        saved = git_head(brain) not in ("", head)  # the commit exists when HEAD moved, whatever a hook said afterwards
        if code == 124:
            git_clear_stale_lock(index, started)
        if not saved:
            restored = git_restore_index(index, backup)
            reason = git_commit_reason(output, code, titles)
            ending = "Nothing was changed." if restored else "Nothing was lost: the notes are still waiting to be saved."
            return git_outcome(False, "commit", f"Not saved: {reason}. {ending}", details, git_card(name, brain))
    remote, ref = target
    code, output = run_git_write(brain, ["push", "--", remote, f"HEAD:{ref}"], GIT_PUSH_TIMEOUT)
    details = f"{details}\n{output}"
    if code != 0:
        return git_outcome(False, "send", f"Saved on this computer, but not sent: {git_push_reason(output, code)}.", details, git_card(name, brain), saved=True)
    return git_outcome(True, "done", "Saved and sent.", details, git_card(name, brain), saved=True)


def git_fetch_reason(output: str, code: int) -> str:
    """Why the check of the online copy failed, in a few plain words."""
    text = output.replace("\r", "")
    if code == 124:
        return "the online copy did not answer in time"
    if code == 127:
        return "Git could not be started"
    if re.search(r"Permission denied|Authentication failed|could not read (Username|Password)|terminal prompts disabled|Host key verification failed", text, re.IGNORECASE):
        return "the online copy refused the connection"
    if re.search(r"Could not resolve host|Network is unreachable|Connection (timed out|refused|reset)|unable to access|Could not read from remote", text, re.IGNORECASE):
        return "the online copy could not be reached (check the network)"
    if re.search(r"does not appear to be a git repository|repository .* not found|No such file or directory|not found", text, re.IGNORECASE):
        return "the online copy could not be found"
    if "index.lock" in text or "cannot lock ref" in text:
        return "another program is using this brain right now"
    return git_first_line(text) or "the online copy did not answer"


def git_fetch_target(brain: Path) -> tuple[str, str] | None:
    """(remote, branch ref) of the current branch's upstream, or None (not a repository, detached, no upstream)."""
    if not (brain / ".git").exists():
        return None
    try:
        branch = run_git(brain, "symbolic-ref", "-q", "--short", "HEAD").decode("utf-8", "replace").strip()
    except TaskError:
        return None
    return git_push_target(brain, branch) if branch else None


def git_fetch_locked(brain: Path) -> str:
    """One real `git fetch --prune` of the brain's upstream remote; the caller holds GIT_LOCK. Records the time and the error in memory.

    Returns "fetched", "failed" (offline, refused, timed out: not an error for the page) or "unavailable" (nothing to fetch from).
    """
    target = git_fetch_target(brain)
    if target is None:
        return "unavailable"
    started = time.monotonic()
    code, output = run_git_write(brain, ["fetch", "--quiet", "--prune", "--", target[0]], GIT_FETCH_TIMEOUT)
    GIT_FETCH_STATE[str(brain)] = {
        "mono": started, "at": datetime.now(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds"),
        "error": "" if code == 0 else f"Could not check the online copy: {git_fetch_reason(output, code)}.",
    }
    return "fetched" if code == 0 else "failed"


def git_fetch(brain: Path, force: bool = False) -> str:
    """Check the online copy of one brain: "fetched", "failed", "throttled" (checked less than 5 minutes ago), "busy" (a save or a pull
    is running: skipped, never waited for) or "unavailable"."""
    state = GIT_FETCH_STATE.get(str(brain))
    if not force and state and time.monotonic() - state["mono"] < GIT_FETCH_EVERY:
        return "throttled"
    if not GIT_LOCK.acquire(blocking=False):
        return "busy"
    try:
        return git_fetch_locked(brain)
    finally:
        GIT_LOCK.release()


def git_fetch_overview(brains: dict[str, Path], current: str, only: str | None = None, force: bool = False) -> dict:
    """Fetch every brain (or `only` one), then the cards as `GET /api/git` gives them plus what each check did."""
    outcomes = {name: git_fetch(path.resolve(), force) for name, path in brains.items() if only in (None, name)}
    return {**git_overview(brains, current), "fetch": outcomes}


def git_pull_reason(output: str, code: int) -> str:
    """Why a fast-forward was refused, in a few plain words."""
    text = output.replace("\r", "")
    if code == 124:
        return "it did not finish in time"
    if code == 127:
        return "Git could not be started"
    if "index.lock" in text:
        return "another program is using this brain right now: try again in a moment"
    clash = re.search(r"(?:local changes to the following files|untracked working tree files) would be overwritten.*?:\n((?:[ \t]+\S.*\n?)+)", text)
    if clash:
        names = [posixpath.splitext(posixpath.basename(line.strip()))[0] or line.strip() for line in clash.group(1).splitlines() if line.strip()]
        shown = ", ".join(f"“{name}”" for name in names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        return f"your changes to {shown} would be overwritten by the online version. Ask your agent to bring them here"
    if re.search(r"Not possible to fast-forward|diverging", text):
        return "this brain and its online copy both have changes the other lacks. Ask your agent to bring them together"
    return git_first_line(text) or "Git refused it"


def git_pull(name: str, brain: Path, version: str) -> dict:
    """Bring the online copy's new commits here by fast-forward only; the caller holds GIT_LOCK.

    Allowed when the card is `behind` with nothing of its own to send (unsaved notes may stay), never when both sides have commits.
    The version is checked against the card the person saw, then the online copy is fetched and the fast-forward runs; the brain's
    hooks run as from a terminal (post-merge). A refusal by Git (unsaved changes it would overwrite) is a 409 and changes nothing.
    """
    card, target, _ = git_inspect(name, brain)
    if card["state"] == "unavailable" or target is None:
        raise TaskError(HTTPStatus.CONFLICT, card["message"])
    if card["version"] != version:
        raise TaskError(HTTPStatus.CONFLICT, GIT_STALE)
    if card["state"] == "behind" and not card["pullable"]:
        raise TaskError(HTTPStatus.CONFLICT, card["message"])
    if card["state"] != "behind":
        raise TaskError(HTTPStatus.CONFLICT, "Nothing to bring here: this brain is up to date.")
    outcome = git_fetch_locked(brain)
    if outcome != "fetched":
        raise TaskError(HTTPStatus.BAD_GATEWAY, f"Not brought here: {git_fetch_info(brain)['fetch_error'] or 'the online copy could not be checked.'}")
    fresh = git_inspect(name, brain)[0]
    if fresh["state"] != "behind" or not fresh["pullable"]:
        raise TaskError(HTTPStatus.CONFLICT, fresh["message"] if fresh["state"] == "behind" else "Nothing to bring here: this brain is up to date.")
    before = git_head(brain)
    code, output = run_git_write(brain, ["merge", "--ff-only", "--no-edit", "@{upstream}"], GIT_PULL_TIMEOUT)
    if git_head(brain) == before:
        raise TaskError(HTTPStatus.CONFLICT, f"Not brought here: {git_pull_reason(output, code)}. Nothing was changed.")
    message = f"Brought {fresh['behind']} {'change' if fresh['behind'] == 1 else 'changes'} here."
    if code != 0:  # the fast-forward happened and a hook said something afterwards
        message += f" A check afterwards reported: {git_first_line(output)}."
    return {**git_outcome(True, "done", message, output, git_card(name, brain)), "pulled": fresh["behind"]}
