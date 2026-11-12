#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Setup checklist of the Work workspace on this machine: what an agent still has to ask, and what the owner has to do.

Two kinds of items:

- settings, which an agent asks the user and writes itself (`set`, or `default` when the user says to skip):
  `defaultBrain` and `artifactsDir`, choices of this machine kept in the ignored `work-config.local.json`
  and validated by `work_config.py`; `brains` and `transcripts_dir`, in the default brain's
  `.data/local-paths.json`; and for each brain `<brain>.owner` (`.data/doctor.json`) and `<brain>.scope`,
  `<brain>.description`, `<brain>.remote`, `<brain>.email` (`.data/brain.json`);
- checks of what only the owner can do (`owner-action`, never written by this script): commands to install,
  the Git author and SSH key of each trust boundary in the home configuration, bootstrap (Git hooks, skills),
  the link to a relocated artifacts folder, `tools/.env` when an enabled own skill reads it, expected brains not
  cloned, a transcripts folder not available on this machine, Obsidian.

A setting is done when its value is there and valid (`defaultBrain` also when the rule of `work_config.py`
resolves it, `artifactsDir` when its folder exists). `recordings_dir` of local-paths.json is read by no tool and
not asked. The skill states (`transcripts.json`, `messages-state.json`, `client-repos.json`, skill mappings) are
versioned with their brain and kept by their skills: not settings.

Commands, from the Work root (WORK_DIR targets another workspace):
  status [--json]      every item: done, missing (with its question and its default) or owner-action;
                       exit 1 while a setting is missing, 2 when a file cannot be read
  set <key> <value>    validate the answer and write it where it belongs
  default <key>        write the default of a missing setting (alias: ignore); refused when there is none
Writes are atomic and keep the other keys, their order, the indentation and the final newline of the file.
Prints no configured value but the defaults it proposes. The Claude Code SessionStart hook prints
`session_block()`; agents without the hook run `status` at the start of a conversation (AGENTS.md).
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import work_config  # next to this script: configuration layers and the default brain rule

WORK = Path(os.environ.get("WORK_DIR", HERE.parents[1])).resolve()
LOCAL = work_config.LOCAL.name
STATE = work_config.STATE.name
ARTIFACTS_DEFAULT = work_config.ARTIFACTS
TRANSCRIPTS_DEFAULT = "Documents/Transcripts"
BRAIN_FIELDS = ("owner", "scope", "description", "remote", "email")
BRAIN_SEED = {"allow": [], "description": "", "email": "", "remote": "", "scope": "", "version": 1}
PERSONAL_NAMES = ("brain-perso", "brain-personal")
GIT_HOOKS = ("pre-commit", "commit-msg", "pre-push")
GIT_TIMEOUT = 2
SCOPE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
PASSWORD_IN_URL = re.compile(r"://[^/@\s]*:[^/@\s]*@")
TOOLS_ENV = re.compile(r"tools/\.env(?![.\w])")
DESCRIPTIONS = {
    "personal": "Personal notes, projects, contacts and career; nothing from work for an employer or a client.",
    "employer": "Work for the employer and its clients: missions, actions, decisions and people; nothing personal.",
    "client": "Work for this one client only; nothing personal and nothing from another client.",
}
SETUP_MAX_WORDS = 500  # the owner-action line is always kept; missing settings beyond it point to `status`
PREAMBLE = (
    "Setup incomplete: before any other work in this conversation, ask the user for each missing item below, "
    "one question at a time, in the user's language, and say its default. Save each answer with "
    "`uv run tools/machine/setup.py set <key> <value>`; when the user says to ignore or skip an item, run "
    "`uv run tools/machine/setup.py default <key>` instead (an item without a default cannot be skipped: say so "
    "and propose the suggestion). Then run `uv run tools/machine/setup.py status`, ask for anything still missing, "
    "and continue with the user's request."
)
IDENTITY = (
    "set the Git author and SSH key of each trust boundary in your home configuration, one ~/.gitconfig-<boundary> "
    "per folder or remote (tools/machine/GIT-IDENTITY.md, tools/machine/gitconfig.example); agents edit it only "
    "with your explicit confirmation"
)


class SetupError(Exception):
    """A file cannot be read, or an answer is refused."""


@dataclass
class Item:
    key: str
    kind: str  # "setting" (asked and written by an agent) or "check" (done by the owner)
    state: str  # "done", "missing" or "owner-action"
    where: str  # where the value lives, or what the owner changes
    why: str  # who reads it
    question: str = ""
    default: str | None = None
    suggestion: str | None = None
    instruction: str = ""
    detail: str = ""
    value: str = ""  # the effective value of a setting, for the tasks-web Settings view; never printed by `status`


def rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_object(root: Path, path: Path) -> tuple[dict[str, Any], str | None]:
    """A JSON object and its text; ({}, None) when the file is absent; SetupError when unreadable or not an object."""
    if not path.exists() and not path.is_symlink():
        return {}, None
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SetupError(f"cannot read {rel(root, path)} ({error.__class__.__name__}): fix it by hand, then rerun") from None
    if not isinstance(data, dict):
        raise SetupError(f"{rel(root, path)}: a JSON object is expected; fix it by hand, then rerun")
    return data, text


def dump(data: dict[str, Any], original: str | None) -> str:
    """JSON text in the layout of `original`: its indentation (or compact form), escapes and final newline."""
    indent: int | str | None = 2
    if original is not None:
        body = original.strip()
        if "\n" not in body:
            indent = None if len(body) > 2 else 2
        else:
            match = re.search(r"\n([ \t]+)\S", body)
            if match:
                indent = "\t" if match.group(1).startswith("\t") else len(match.group(1))
    text = json.dumps(data, indent=indent, ensure_ascii=original is not None and "\\u" in original)
    return text + ("\n" if original is None or original.endswith("\n") else "")


def write_atomic(path: Path, text: str) -> None:
    """Replace `path` in one step (temporary file in the same folder, then rename), keeping its permissions."""
    if path.is_symlink():
        path = path.resolve()
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def update_file(root: Path, path: Path, changes: dict[str, Any], seed: dict[str, Any] | None = None) -> None:
    """Set keys of a JSON object file, keeping the others, their order and the layout; a sorted file stays sorted."""
    data, text = read_object(root, path)
    if text is None and seed is not None:
        data = dict(seed)
    was_sorted = list(data) == sorted(data)
    data.update(changes)
    if was_sorted and len(data) > 1:
        data = dict(sorted(data.items()))
    write_atomic(path, dump(data, text))


def escape_pattern(value: str) -> str:
    """An fnmatch pattern that matches exactly `value`."""
    return re.sub(r"([*?\[])", r"[\1]", value)


class Workspace:
    """Everything the checklist reads, loaded once: local layer, brains, their .data files, Git answers (cached)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.local, _ = read_object(root, root / LOCAL)
        self.brains = work_config.find_brains(root)
        self.names = [brain.name for brain in self.brains]
        self.default_problem = ""
        try:
            self.default = work_config.default_brain(root)
        except work_config.ConfigError as error:
            self.default, self.default_problem = None, str(error)
        if self.default is None and not self.default_problem and self.brains:
            self.default_problem = f"several brains ({', '.join(self.names)}) and none named brain/"
        self.ordered = sorted(self.brains, key=lambda brain: (brain != self.default, brain.name))
        self.files: dict[tuple[str, str], dict[str, Any]] = {}
        for brain in self.brains:
            for name in ("brain.json", "doctor.json"):
                self.files[(brain.name, name)] = read_object(root, brain / ".data" / name)[0]
        self.paths = read_object(root, self.default / ".data/local-paths.json")[0] if self.default else {}
        self.has_git = shutil.which("git") is not None
        self._git: dict[tuple[str, ...], str] = {}

    def git(self, repo: Path, *args: str) -> str:
        """Stdout of a local git command (cached), "" on any failure."""
        key = (str(repo), *args)
        if key not in self._git:
            output = ""
            if self.has_git:
                try:
                    result = subprocess.run(
                        ["git", "-C", str(repo), *args],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=GIT_TIMEOUT,
                        stdin=subprocess.DEVNULL,
                        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
                    )
                    output = result.stdout.strip() if result.returncode == 0 else ""
                except (OSError, subprocess.SubprocessError):
                    output = ""
            self._git[key] = output
        return self._git[key]

    def repo_git(self, repo: Path, *args: str) -> str:
        """Like `git`, but "" when `repo` is not a Git repository itself (git would answer for the enclosing Work)."""
        return self.git(repo, *args) if (repo / ".git").exists() else ""

    def field(self, brain: Path, field: str) -> str:
        source = self.files[(brain.name, "doctor.json" if field == "owner" else "brain.json")]
        value = source.get(field)
        return value.strip() if isinstance(value, str) else ""

    def paths_file(self) -> str:
        return f"{self.default.name}/.data/local-paths.json" if self.default else "<default brain>/.data/local-paths.json"


# --- Settings -----------------------------------------------------------------------------------------------


def artifacts_path(root: Path, value: Any) -> Path:
    """The folder an `artifactsDir` value names, as `work_config.artifacts_dir` resolves it (ConfigError if invalid)."""
    text = work_config.check_artifacts_value(value, f"{LOCAL}: artifactsDir")
    path = Path(text).expanduser()
    return Path(os.path.normpath(path if path.is_absolute() else root / path))


def default_brain_item(ws: Workspace) -> Item:
    item = Item(
        "defaultBrain", "setting", "done", LOCAL, "every tool that acts on a brain when none is named",
        question=f"Which brain should the tools use when none is named ({', '.join(ws.names)})?",
    )
    if ws.default is not None:
        item.value = ws.default.name
    if ws.default is None:
        scopes = {brain.name: ws.field(brain, "scope") or scope_default(brain) or "" for brain in ws.ordered}
        item.state, item.detail = "missing", ws.default_problem
        item.suggestion = next((name for name, scope in scopes.items() if scope != "personal"), ws.names[0])
    return item


def artifacts_item(ws: Workspace) -> Item:
    item = Item(
        "artifactsDir", "setting", "done", LOCAL, "bootstrap.sh, doctor.py and the Bash guard: where deliverables and received files live",
        question="Where should the artifacts folder (deliverables, received files; no Git backup) live: "
        "artifacts/ in Work, or a synced folder (absolute path)?",
        default=ARTIFACTS_DEFAULT,
    )
    if "artifactsDir" not in ws.local:
        item.state, item.detail = "missing", "not set"
        return item
    try:
        path = artifacts_path(ws.root, ws.local["artifactsDir"])
    except work_config.ConfigError as error:
        item.state, item.detail = "missing", str(error)
        return item
    item.value = str(ws.local["artifactsDir"])
    if not path.is_dir():
        item.state, item.detail = "missing", "the configured folder is not on this machine"
    return item


def brains_item(ws: Workspace) -> Item:
    item = Item(
        "brains", "setting", "done", ws.paths_file(), "doctor.py and brain-state.py (cr-reunion): the brains every machine must have",
        question="Which brains must every machine have (folder names, comma-separated)?",
        default=", ".join(brain.name for brain in ws.ordered),
    )
    value = ws.paths.get("brains")
    valid = isinstance(value, list) and value and all(isinstance(name, str) and work_config.BRAIN_NAME.fullmatch(name) for name in value)
    if valid:
        item.value = ", ".join(value)
    if ws.default is None:
        item.state, item.detail = "missing", "answer defaultBrain first"
    elif not valid:
        item.state, item.detail = "missing", "not set" if value is None else "not a list of brain folder names"
    return item


def transcripts_item(ws: Workspace) -> Item:
    item = Item(
        "transcripts_dir", "setting", "done", ws.paths_file(), "brain-state.py transcripts --new, used by cr-reunion",
        question="Which folder holds your meeting transcripts (path under your home folder)?",
        default=TRANSCRIPTS_DEFAULT,
    )
    value = ws.paths.get("transcripts_dir")
    if isinstance(value, str):
        item.value = value.strip()
    if ws.default is None:
        item.state, item.detail = "missing", "answer defaultBrain first"
    elif not isinstance(value, str) or not value.strip():
        item.state, item.detail = "missing", "not set"
    return item


def scope_default(brain: Path) -> str | None:
    return "personal" if brain.name in PERSONAL_NAMES else None


def brain_items(ws: Workspace, brain: Path) -> list[Item]:
    name = brain.name
    specs = {
        "owner": ("doctor.json", "action.py, decision.py, brain-state.py person and tasks-web: owner of the board and of new actions",
                  f"Whose name owns the actions of {name} (first and last name)?"),
        "scope": ("brain.json", "the choice of a brain (brain-state.py brains) and the employer-name scan (check-no-client)",
                  f"What is the scope of {name}: personal, employer or client?"),
        "description": ("brain.json", "agents choose the brain of new content from it",
                        f"In one sentence, what does {name} hold, and what must it never hold?"),
        "remote": ("brain.json", "doctor.py and the pre-push hook check the origin URL against it",
                   f"Which Git remote URLs may {name} push to (fnmatch pattern)?"),
        "email": ("brain.json", "doctor.py and the pre-push hook check the commit e-mail against it",
                  f"Which commit e-mail must {name} use (fnmatch pattern)?"),
    }
    items = []
    for field in BRAIN_FIELDS:
        file, why, question = specs[field]
        item = Item(f"{name}.{field}", "setting", "done", f"{name}/.data/{file}", why, question=question)
        item.value = ws.field(brain, field)
        if not item.value:
            item.state, item.detail = "missing", "not set"
            item.default, item.suggestion = brain_default(ws, brain, field)
        items.append(item)
    return items


def brain_default(ws: Workspace, brain: Path, field: str) -> tuple[str | None, str | None]:
    """(default, suggestion when there is no default) of a brain field."""
    if field == "owner":
        others = [ws.field(other, "owner") for other in ws.ordered if other != brain]
        known = next((owner for owner in others if owner), "") or ws.repo_git(brain, "config", "--get", "user.name")
        return (known, None) if known else (None, "the owner's first and last name")
    if field == "scope":
        default = scope_default(brain)
        return (default, None) if default else (None, "employer")
    if field == "description":
        scope = ws.field(brain, "scope") or scope_default(brain) or ""
        text = DESCRIPTIONS.get(scope.casefold())
        return (text, None) if text else (None, "one sentence: what it holds, and what it must never hold")
    if field == "remote":
        url = ws.repo_git(brain, "remote", "get-url", "origin")
        return (escape_pattern(url), None) if url else (None, "git@<host>:<account>/* (where its private repository will live)")
    email = ws.repo_git(brain, "config", "--get", "user.email")
    return (escape_pattern(email), None) if email else (None, "*@<your e-mail domain>")


# --- Checks of what only the owner can do -------------------------------------------------------------------


def check(key: str, ok: bool, where: str, why: str, instruction: str, detail: str = "") -> Item:
    return Item(key, "check", "done" if ok else "owner-action", where, why, instruction=instruction, detail="" if ok else detail)


def resolved_config(ws: Workspace) -> dict[str, Any] | None:
    """The resolved skill configuration of this workspace, None when invalid (doctor.py reports it) or elsewhere."""
    if work_config.ROOT != ws.root:
        return None
    try:
        return work_config.resolve()
    except (work_config.ConfigError, OSError):
        return None


def checks(ws: Workspace) -> list[Item]:
    root = ws.root
    items = [
        check("command.git", ws.has_git, "this machine", "Work and every brain are Git repositories", "install Git (https://git-scm.com/downloads)"),
        check("command.uv", shutil.which("uv") is not None, "this machine", "every script runs with uv run",
              "install uv (https://docs.astral.sh/uv/getting-started/installation/)"),
    ]
    config = resolved_config(ws)
    if config is not None and work_config.enabled_third_party(config):
        items.append(check("command.npx", shutil.which("npx") is not None, "this machine", "update.sh installs the third-party skills with npx",
                           "install Node.js (npx), then run ./tools/machine/update.sh"))
    if not ws.brains:
        items.append(check("install", False, "Work root", "the tools act on a brain", "run ./tools/machine/install.sh (clones your brain or creates a blank one)"))
        return items

    repos = [("Work", root), *[(brain.name, brain) for brain in ws.ordered]]
    unhooked = [label for label, repo in repos if (repo / ".git").is_dir() and not all((repo / ".git/hooks" / hook).is_file() for hook in GIT_HOOKS)]
    stamped = (root / STATE).is_file()
    problems = ([f"Git hooks missing in {', '.join(unhooked)}"] if unhooked else []) + ([] if stamped else [f"no {STATE}"])
    items.append(check("bootstrap", not problems, "Work root", "Git hooks of Work and of every brain, skills and their links",
                       "run ./tools/machine/bootstrap.sh from the Work root (an agent may run it with your agreement)", "; ".join(problems)))

    if ws.has_git:
        wrong = []
        for label, repo in repos:
            if not (repo / ".git").exists():
                continue
            email = ws.git(repo, "config", "--get", "user.email")
            pattern = ws.field(repo, "email") if repo != root else ""
            if not email:
                wrong.append(f"{label}: no commit e-mail")
            elif pattern and not fnmatch.fnmatchcase(email, pattern):
                wrong.append(f"{label}: commit e-mail outside the email pattern of its brain.json")
        items.append(check("git-identity", not wrong, "home Git configuration", "commits and pushes use the identity of their trust boundary",
                           IDENTITY, "; ".join(wrong)))

    if "artifactsDir" in ws.local:
        try:
            folder = artifacts_path(root, ws.local["artifactsDir"])
        except work_config.ConfigError:
            folder = None
        if folder is not None and folder.is_dir() and not folder.resolve().is_relative_to(root):
            link = root / ARTIFACTS_DEFAULT
            linked = link.is_symlink() and link.resolve() == folder.resolve()
            items.append(check("artifacts-link", linked, "Work root", "the brains link to ../artifacts/…, which must reach the configured folder",
                               "move the content of artifacts/ into the configured folder (nothing deleted), remove the empty artifacts/, "
                               "then run ./tools/machine/bootstrap.sh, which links artifacts/ to it",
                               "artifacts/ is a real folder" if link.is_dir() and not link.is_symlink() else "artifacts/ does not link to it"))

    if config is not None:
        readers = []
        for name, skill in work_config.enabled_own(config).items():
            with contextlib.suppress(OSError, UnicodeDecodeError):
                if TOOLS_ENV.search((skill["path"] / "SKILL.md").read_text(encoding="utf-8")):
                    readers.append(name)
        if readers:
            skills = ", ".join(sorted(readers))
            items.append(check("tools-env", (root / "tools/.env").is_file(), "tools/.env (ignored by Git)", f"the tokens of {skills}",
                               f"create tools/.env with the variables listed by {skills} and fill in the values yourself; agents never read or write it",
                               "tools/.env missing"))

    if ws.default is not None:
        expected = ws.paths.get("brains")
        if isinstance(expected, list):
            absent = [name for name in expected if isinstance(name, str) and not work_config.is_brain(root / name)]
            if absent:
                items.append(check("expected-brains", False, "Work root", "brains listed in local-paths.json",
                                   f"clone {', '.join(absent)} at the Work root with the identity of its boundary, then run ./tools/machine/bootstrap.sh; "
                                   "or remove it with `setup.py set brains <names>`", "not at the Work root"))
        value = ws.paths.get("transcripts_dir")
        if isinstance(value, str) and value.strip() and value.strip() != TRANSCRIPTS_DEFAULT:
            items.append(check("transcripts-folder", (Path.home() / value.strip()).is_dir(), ws.paths_file(), "cr-reunion reads the transcripts there",
                               "make the transcripts folder (transcripts_dir, under your home folder) available on this machine: sync or create it, "
                               "or change it with `setup.py set transcripts_dir <path>`", "not found on this machine"))

    items.append(check("obsidian", (root / ".obsidian").is_dir(), "Obsidian", "the brains and the tasks board are read in Obsidian",
                       "open Work/ in Obsidian as the only vault and set it up by hand: kit/obsidian/README.md"))
    return items


def collect(root: Path) -> list[Item]:
    """Every item of the checklist, settings first; SetupError when a file it reads cannot be read."""
    ws = Workspace(root)
    return items_of(ws)


def items_of(ws: Workspace) -> list[Item]:
    items: list[Item] = []
    if ws.brains:
        items.append(default_brain_item(ws))
    items.append(artifacts_item(ws))
    if ws.brains:
        items += [brains_item(ws), transcripts_item(ws)]
        for brain in ws.ordered:
            items += brain_items(ws, brain)
    return items + checks(ws)


# --- Writing answers ----------------------------------------------------------------------------------------


def one_line(value: str, label: str, limit: int) -> str:
    text = " ".join(value.split())
    if not text:
        raise SetupError(f"{label}: an empty answer is not a value")
    if len(text) > limit:
        raise SetupError(f"{label}: {limit} characters at most")
    return text


def no_space(value: str, label: str, limit: int) -> str:
    text = value.strip()
    if not text or any(char.isspace() for char in text) or len(text) > limit:
        raise SetupError(f"{label}: one word without spaces, {limit} characters at most")
    return text


def write_local(ws: Workspace, key: str, value: str) -> None:
    """Set a machine-only key of work-config.local.json, validated with the rules of work_config.py."""
    path = ws.root / LOCAL
    data, text = read_object(ws.root, path)
    data = data if "version" in data else {"version": 1, **data}
    data[key] = value
    try:
        work_config.parse_layer(data, LOCAL, local=True)
    except work_config.ConfigError as error:
        raise SetupError(f"{LOCAL} would be invalid: {error}") from None
    write_atomic(path, dump(data, text))


def set_default_brain(ws: Workspace, value: str) -> list[str]:
    name = value.strip()
    try:
        work_config.check_brain_name(name, "defaultBrain")
    except work_config.ConfigError as error:
        raise SetupError(str(error)) from None
    if not work_config.is_brain(ws.root / name):
        raise SetupError(f"{name} is not a brain at the Work root (found: {', '.join(ws.names) or 'none'})")
    write_local(ws, "defaultBrain", name)
    return []


def set_artifacts(ws: Workspace, value: str) -> list[str]:
    text = value.strip()
    try:
        folder = artifacts_path(ws.root, text)
    except work_config.ConfigError as error:
        raise SetupError(str(error)) from None
    inside = folder.is_relative_to(ws.root)
    notes = []
    if folder.exists() and not folder.is_dir():
        raise SetupError(f"artifactsDir: {folder} is not a folder")
    if not folder.exists():
        if not inside:
            raise SetupError(f"artifactsDir: {folder} does not exist: create it, or move the artifacts folder there, then answer again")
        folder.mkdir(parents=True)
        notes.append(f"created {rel(ws.root, folder)}/")
    write_local(ws, "artifactsDir", text)
    link = ws.root / ARTIFACTS_DEFAULT
    if not folder.resolve().is_relative_to(ws.root) and not (link.is_symlink() and link.resolve() == folder.resolve()):
        notes.append("artifacts/ does not link to it yet: move its content there (nothing deleted), remove the empty artifacts/, "
                     "then run ./tools/machine/bootstrap.sh")
    return notes


def set_brains(ws: Workspace, value: str) -> list[str]:
    if ws.default is None:
        raise SetupError("no default brain: answer defaultBrain first")
    names: list[str] = []
    for name in re.split(r"[,\s]+", value.strip()):
        if name and name not in names:
            try:
                names.append(work_config.check_brain_name(name, "brains"))
            except work_config.ConfigError as error:
                raise SetupError(str(error)) from None
    if ws.default.name not in names:
        raise SetupError(f"brains: the list must include the default brain {ws.default.name}")
    update_file(ws.root, ws.default / ".data/local-paths.json", {"brains": names})
    absent = [name for name in names if not work_config.is_brain(ws.root / name)]
    return [f"not at the Work root yet: {', '.join(absent)} (clone it)"] if absent else []


def set_transcripts(ws: Workspace, value: str) -> list[str]:
    if ws.default is None:
        raise SetupError("no default brain: answer defaultBrain first")
    text = value.strip()
    if not text or "\0" in text:
        raise SetupError("transcripts_dir: a folder path is expected")
    path = Path(text).expanduser()
    home = Path.home()
    if path.is_absolute():
        for base in (home, home.resolve()):
            with contextlib.suppress(ValueError):
                path = path.relative_to(base)
                break
        else:
            raise SetupError("transcripts_dir: the folder must be under your home folder (it is stored relative to it)")
    relative = PurePosixPath(os.path.normpath(path).replace(os.sep, "/"))
    if str(relative) in ("", ".") or relative.parts[0] == "..":
        raise SetupError("transcripts_dir: a folder under your home folder is expected")
    folder = home / relative
    if folder.resolve().is_relative_to(ws.root.resolve()):
        raise SetupError("transcripts_dir: input folders stay outside the workspace")
    update_file(ws.root, ws.default / ".data/local-paths.json", {"transcripts_dir": relative.as_posix()})
    return [] if folder.is_dir() else ["the folder is not on this machine yet"]


def set_brain_field(ws: Workspace, brain: Path, field: str, value: str) -> list[str]:
    label = f"{brain.name}.{field}"
    notes = []
    if field == "owner":
        update_file(ws.root, brain / ".data/doctor.json", {"owner": one_line(value, label, 120)})
        return notes
    if field == "scope":
        text = value.strip().lower()
        if not SCOPE.fullmatch(text):
            raise SetupError(f"{label}: a short lowercase label, such as personal, employer or client")
    elif field == "description":
        text = one_line(value, label, 500)
    elif field == "remote":
        text = no_space(value, label, 300)
        if PASSWORD_IN_URL.search(text):
            raise SetupError(f"{label}: never a password in a URL")
        origin = ws.repo_git(brain, "remote", "get-url", "origin")
        if origin and not fnmatch.fnmatchcase(origin, text):
            notes.append(f"the current origin of {brain.name} does not match this pattern (doctor.py reports it)")
    else:
        text = no_space(value, label, 200)
        if "@" not in text:
            raise SetupError(f"{label}: an e-mail pattern such as *@acme.example")
        email = ws.repo_git(brain, "config", "--get", "user.email")
        if email and not fnmatch.fnmatchcase(email, text):
            notes.append(f"the commit e-mail of {brain.name} does not match this pattern: see the git-identity check")
    update_file(ws.root, brain / ".data/brain.json", {field: text}, seed=BRAIN_SEED)
    return notes


def apply(root: Path, key: str, value: str | None) -> list[str]:
    """Write `value` for the setting `key` (None: its default); return the lines to print."""
    ws = Workspace(root)
    items = {item.key: item for item in items_of(ws)}
    item = items.get(key)
    if item is None:
        settings = [name for name, entry in items.items() if entry.kind == "setting"]
        raise SetupError(f"unknown setting {key!r}; settings: {', '.join(settings)}")
    if item.kind == "check":
        raise SetupError(f"{key} is done by the owner, not a setting: {item.instruction}")
    if value is None:
        if item.state == "done":
            return [f"{key}: already set; nothing written (use set to change it)"]
        if item.default is None:
            hint = f"; suggestion: {item.suggestion}" if item.suggestion else ""
            raise SetupError(f"{key} has no sensible default and cannot be skipped: ask the user for a value{hint}")
        value = item.default
    if key == "defaultBrain":
        notes = set_default_brain(ws, value)
    elif key == "artifactsDir":
        notes = set_artifacts(ws, value)
    elif key == "brains":
        notes = set_brains(ws, value)
    elif key == "transcripts_dir":
        notes = set_transcripts(ws, value)
    else:
        name, field = key.split(".", 1)
        notes = set_brain_field(ws, root / name, field, value)
    left = sum(entry.state == "missing" for entry in collect(root))
    return [f"{key}: written to {item.where}", *[f"note: {note}" for note in notes],
            f"Setup: {left} setting(s) still missing" if left else "Setup: no setting missing"]


# --- Output -------------------------------------------------------------------------------------------------


def default_text(item: Item) -> str:
    if item.default is not None:
        return f"Default: {item.default.rstrip('.')}."
    return f"No default (suggest: {item.suggestion})." if item.suggestion else "No default."


def session_block(root: Path) -> str:
    """Text for the start of a conversation: the missing settings to ask, the owner actions; "" when all is done."""
    items = collect(root)
    missing = [item for item in items if item.state == "missing"]
    owner = [item for item in items if item.state == "owner-action"]
    if not missing and not owner:
        return ""
    owner_line = ""
    if owner:
        prefix = "To do by the owner, not blocking" if missing else "Setup: to do by the owner, not blocking"
        actions = [f"`{item.key}`: {item.instruction}" + (f" ({item.detail})" if item.detail else "") for item in owner]
        owner_line = f"{prefix} (mention it once, briefly): " + "; ".join(actions) + "."
    lines: list[str] = []
    if missing:
        budget = SETUP_MAX_WORDS - len(owner_line.split())
        lines.append(PREAMBLE)
        words = len(PREAMBLE.split())
        for item in missing:
            detail = f" ({item.detail})" if item.detail and item.detail != "not set" else ""
            line = f"- `{item.key}`: {item.question}{detail} {default_text(item)}"
            if words + len(line.split()) > budget:
                lines.append("- more: `uv run tools/machine/setup.py status`")
                break
            lines.append(line)
            words += len(line.split())
    return "\n".join([*lines, owner_line] if owner_line else lines)


def print_status(items: list[Item]) -> None:
    counts = {state: sum(item.state == state for item in items) for state in ("missing", "owner-action", "done")}
    print(f"Setup: {counts['missing']} missing, {counts['owner-action']} to do by the owner, {counts['done']} done.")
    width = max(len(item.key) for item in items)
    for item in items:
        print(f"{item.state:<12}  {item.key:<{width}}  {item.where}")
        if item.state == "missing":
            print(f"    question: {item.question}")
            print(f"    {default_text(item)}")
            if item.detail:
                print(f"    missing: {item.detail}")
            print(f"    read by: {item.why}")
        elif item.state == "owner-action":
            print(f"    to do by the owner: {item.instruction}")
            if item.detail:
                print(f"    found: {item.detail}")
    if counts["missing"]:
        print("Answer with `uv run tools/machine/setup.py set <key> <value>`; skip with `uv run tools/machine/setup.py default <key>` (alias: ignore).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status", help="every item: done, missing (question and default) or owner-action")
    status_parser.add_argument("--json", action="store_true", help="machine-readable output")
    set_parser = sub.add_parser("set", help="validate an answer and write it where it belongs")
    set_parser.add_argument("key")
    set_parser.add_argument("value", nargs="+", help="the answer (several words are joined with spaces)")
    default_parser = sub.add_parser("default", aliases=["ignore"], help="write the default of a missing setting")
    default_parser.add_argument("key")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            items = collect(WORK)
            missing = sum(item.state == "missing" for item in items)
            if args.json:
                summary = {state: sum(item.state == state for item in items) for state in ("missing", "owner-action", "done")}
                listed = [{key: value for key, value in asdict(item).items() if key != "value"} for item in items]  # no configured value
                print(json.dumps({"complete": not missing, "counts": summary, "items": listed}, indent=2, ensure_ascii=False))
            else:
                print_status(items)
            return 1 if missing else 0
        value = " ".join(args.value) if args.command == "set" else None
        print("\n".join(apply(WORK, args.key, value)))
        return 0
    except (SetupError, OSError) as error:
        print(f"setup error: {error}", file=sys.stderr)
        return 2 if args.command == "status" else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 even through a pipe on Windows
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
