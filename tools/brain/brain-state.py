#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2024.1; sys_platform == 'win32'"]  # zoneinfo has no time zone database of its own on Windows
# ///
"""Map the brains of the workspace and merge their skill states.

A brain is a directory at the Work root named `brain` or `brain-*` that holds
an AGENTS.md and a .data/ folder. Each transcript belongs to exactly one brain:
its state lives only in that brain's .data/transcripts.json. A transcript is
new when no brain lists it.

The default brain (`brain/`, else the only brain, or the one named by `defaultBrain`
in work-config.local.json: see tools/machine/work_config.py) holds the shared
configuration: the input folders in .data/local-paths.json and, optionally, the
list of brains expected on every machine (`"brains": ["brain", "brain-perso"]`).
A missing expected brain stops the tool, so its transcripts never come back as new elsewhere.

Each brain is a trust boundary declared in its own .data/brain.json (`scope`,
`description`, ...). `brains` prints the scope and the description next to each
brain, so that an agent can pick the brain where new content belongs.

Commands (from the Work root, `uv run tools/brain/brain-state.py <command> --help` for details):

    map [--json] [--brain NAME] [--archived | --all]   where everything is: brains, clients, projects, pages, registers
    brief PROJECT [--brain NAME] [--words N] [--limit N] [--decisions N] [--archived] [--json]
                                          one project in about 40 lines, to load at the start of a task
    due [--days N] [--brain NAME] [--json]             late actions and those due within N days (default 7)
    changes --since DATE|Nd [--project P] [--limit N] [--brain NAME] [--json]
                                          what the registers and timelines date since a day
    find TERM [--project P] [--in KIND[,KIND]] [--per-file N] [--limit N] [--archived | --all] [--brain NAME] [--json]
                                          search every Markdown page of the brains, ranked by kind
    section FILE[:LINE] [HEADING] [--words N] [--brain NAME] [--json]
                                          the outline of a page, or one of its sections
    person NAME [--words N] [--limit N] [--brain NAME] [--json]
                                          who someone is and the open actions they carry
    archive PROJECT|clients/CLIENT [--write] [--brain NAME] [--json]    move a finished project or client into an archive/ folder
    unarchive PROJECT|clients/CLIENT [--write] [--brain NAME] [--json]  move it back, the exact inverse
    brains                                the brains found, with their scope and description
    transcripts [--new | --where FILE]    merged transcript states

`map` is the first command of a session: it replaces the exploration calls that locate the
brain, client, mission and register to work in. One block per brain (name, scope, `default`
mark, number of people pages, lines waiting in `inbox/inbox.md`), then one line per project,
grouped by client (with the client index page) and `internal`. A project is a folder holding
`state/actions.md`; its line gives:

    name, register ID prefix, actions to do / in progress / waiting / done (by `[ ]` `[/]` `[w]`
    `[x]`), `late` = unfinished actions whose `📅` date is before today (Europe/Paris), `dec` =
    decisions still proposed in `state/decisions.md`, `last` = date of the latest `## Timeline`
    entry of the page, and the page path from the Work root (`<project>/<project>.md`, flagged
    when missing). Archived projects (in the `archive/` folder at their level: `clients/<client>/missions/archive/`,
    `internal/archive/`, `clients/archive/<client>/` for a whole client; also the earlier `projects/archive/` and
    `projects/clients/<client>/archive/`) keep their label and are hidden, and counted on a last line per brain; `--archived` shows only them (and the clients
    of their missions), `--all` both, flagged `[archived]`. `--brain NAME` keeps one brain.
    `--json` prints the same data with stable keys (`today`, `scope`, then per brain `name`, `default`,
    `scope`, `people`, `inbox_lines`, `clients`, `internal`, `left_out` (the projects not shown);
    per project `label`, `name`, `kind`,
    `client`, `archived`, `page`, `register`, `prefix`, `actions`, `decisions_proposed`,
    `last_timeline`). Read-only, no network. `inbox_lines` counts the non-empty lines below the
    first `---` of `inbox/inbox.md`, else below its title and quote, ignoring triage log lines.

The context commands (`brief`, `due`, `changes`, `find`, `section`, `person`) are read-only, need no
network and never run Git; they read the registers with the parsers of `action.py` and `decision.py`.
They exist so that an answer loads command output, not whole files. PROJECT is named as for
`action.py list --project` (register, project folder, `client/mission` or label) and looked up in every
brain, or in `--brain NAME`. Paths are printed from the Work root (`brain-acme/projects/…`).

An archived project (a finished project moved whole by `archive`) is outside these commands: `due`,
`changes` and `person` never read it, `brief` and `changes --project` refuse it (the error says how to
read it and how to bring it back), `find` never searches it, not even when nothing else matches. Two
explicit ways read it: `brief PROJECT --archived`, and `find TERM --archived` (the archived projects
only; `--all`: everything; `--project` names one with either). `section` reads any file it is given.

    brief    the project page's `## Current state` section, else its first summary section (`## Summary`,
             `## En bref`, `## Context`; the output says which), cut after `--words` words; the action and
             decision counts; the late actions then the other open ones, one line each (ID, state, due
             date, owner, title), `--limit` in all; the proposed and accepted decisions, most recent
             first, `--decisions` at most; the five latest timeline entries (page, then `journal/`); the
             repositories that the brain's catalog `.data/client-repos.json` assigns to the project (names
             only, present on this machine when `<Work>/<path>/.git` exists; the line is left out when the
             catalog names none) with the `client-repos.py list --project` command; and
             at most four commands that load one part of the project, never a whole file: the outline of
             its page (`section`), its open actions (`action.py list --project … --state open --table`),
             its decisions (`decision.py list --project … --table`) and the latest index of its sources.
             Defaults: `--words 150`, `--limit 10`, `--decisions 5`.
    due      per project, the unfinished actions whose `📅` date is past (`late`) or within `--days` days.
    changes  per project, newest first: `timeline` entries (page and `journal/YYYY-MM.md`), actions
             `created` (`created:` stamp, else `➕`) or `closed` (`✅`/`❌` date, live register and
             `actions-archive-YYYY.md`), `decision` (date of the title) and `settled` (date of its
             Accepted, Rejected or Superseded by line). Only dates written in the files count. With
             `--project P`, every event of the period; otherwise 20 events per project (`--limit`), cut
             by whole days, most recent first, then `+N more` with the dates left and the `--project`
             command that shows them.
    find     a literal piece of text, compared without case and accents (and with plain apostrophes,
             quotes, dashes and spaces for the typographic ones), in every Markdown file of the brains
             but `skills/` and the hidden folders, or of one project folder with `--project P`. Each file
             once, `kind  path`, then its hits indented, `:line  excerpt`; the excerpt is 160 characters at
             most, centred on the match. In a register, one hit per action or decision: its first line
             when it matches, else its first matching sub-bullet (source, history), starting with the
             action's `ID [state]` or `no. N [state]`; the blocks whose first line matches come first,
             then the rest in line order. Kinds, in the order they are printed: `action`
             (`state/actions.md`), `decision` (`state/decisions.md`), `page` (project and client pages,
             glossaries and the other pages of the brain), `person` (`people/`), `workstream`, `note`
             (`notes/`, `handoffs/`, `inbox/`), `journal` and `source` (`sources/**`). Journals and
             sources come most recent first (date in the path), the rest by file then line. 1 hit per
             file (`--per-file N`, 0 for all), the last one ending with `(+N in this file)`; `--limit`
             hits in all (default 40), then one line counting what is left by kind. `--in` keeps some
             kinds. The archives of the live content (action archives `actions-archive-YYYY.md`,
             `people/archive/` and the other `archive/` folders) are read with `--all`, and on
             their own when nothing else matches; the archived projects never are: `--archived` searches
             them alone, `--all` everything. The `no match` line counts the archived projects left out.
    section  FILE is a path as `find` and `brief` print it (from a brain with `--brain NAME` too); only a
             Markdown file inside a brain is read. Alone: the outline (front matter, then one line per
             heading with its line number and the words of its section, then the total). `FILE:LINE`:
             the section that holds that line. `FILE HEADING`: the section whose title is HEADING, else
             starts with it, else contains it, without case and accents; `summary` stands for the first
             of Summary, Résumé, En bref, Current state, État actuel; several matches are listed (exit
             code 1). A section runs to the next heading of the same or a higher level and is cut after
             `--words` words (default 400) with `(truncated, N more words: path:line)`. `FILE:LINE`
             prints a window of 150 words (`--words`) around the line: from the top of its section when
             the line ends in the first two thirds of it, else from a third of the window above the line.
    person   NAME is the slug of a `people/` page, or words of the name or of one alias, without case and
             accents; several pages are listed (exit code 1), an unknown name gets the closest ones. It
             prints the identity part of the page (name, role, organization, aliases, missions, the lines
             under the title and the `Role and scope` section), cut after `--words` words (default 120),
             then the open actions the person carries in every brain (ID, state, due date, title,
             project; `--limit`, default 10), then the page path. An owner counts when it is the full
             name or an alias, or a first name that one person only bears; a first name shared by several
             people pages is listed apart, with the people it may stand for. `A / B`, `A, then B` name
             both. Each name is looked up among the people of the register's brain, then of the others.
             The owner of a brain (`BRAIN_OWNER`, else `owner` in its `.data/doctor.json`) counts as one
             more person, so that its name is never taken for a people page; `person` prints the owner's
             open actions too, with the profile `me/about-me.md` as the page. Pages of `people/archive/`
             are used only when no other page bears the name.

`archive` and `unarchive` are the only commands that write. PROJECT is named as for `brief`, or
`clients/<client>` for a whole client, or given as a folder path (from the Work root, a brain, or absolute;
a folder without a register too). `archive` moves, with the filesystem (nothing is staged), into the
`archive/` folder at its own level, created when needed: a client mission
`projects/clients/<client>/missions/<mission>/` to `projects/clients/<client>/missions/archive/<mission>/`
(the client page stays), an internal project `projects/internal/<project>/` to
`projects/internal/archive/<project>/`, a whole client `projects/clients/<client>/` to
`projects/clients/archive/<client>/` with all its missions (archiving the last mission of a client never
archives the client). A project in an earlier place (`projects/archive/<project>/`,
`projects/clients/<client>/archive/<mission>/`) is filed in the new one. It refuses while an action of
the project, or of any mission of the client, is still to do, in progress or waiting (it lists them:
close or cancel them first), `internal/setup`, an archived project, and a target that exists; `unarchive`
refuses a mission of an archived client (unarchive the client). It rewrites the relative Markdown links
of the other files of the brain that point into the folder and, the folder being one level deeper, those
inside it that point out, never in code: a target written as the shortest path stays the shortest,
another keeps its form (an `archive` segment inserted or removed where it enters the folder, one `../`
more or less inside it), so `unarchive`, the exact inverse (it also removes an `archive/` folder left
empty), gives every file back byte for byte. It lists the mentions of the old path that are not links (a `tasks.md` query, `.data/*.json`) and
leaves them as they are. Without `--write` it prints what would move and change; with it, it then runs
`tools/brain/check-links.py --allow-missing-local` on that brain and reports it (exit code 1 when the
check fails). `--json`: `command`, `brain`, `project`, `kind` (`mission`, `internal`, `client`), `from`, `to`, `write`, `moved`, `created_dirs`,
`removed_dirs`, `files_changed`, `links` (`file`, `line`, `from`, `to`), `mentions_left`, `link_check`.

Run from the Work root with `uv run tools/brain/brain-state.py`. Set WORK_DIR to use
another workspace and TRANSCRIPTS_DIR to override the transcript folder; ACTION_NOW
(`YYYY-MM-DD HH:MM`) fixes the clock of `map`, `brief`, `due`, `changes` and `person`, as for `action.py`.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


WORK = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parents[2])).resolve()
_spec = importlib.util.spec_from_file_location("work_config", Path(__file__).resolve().parents[1] / "machine/work_config.py")
assert _spec and _spec.loader
work_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(work_config)  # owns the rule of what a brain is and which one is the default


def default_brain() -> Path | None:
    """The default brain of the Work root (None: no brain, or several and no `defaultBrain` setting)."""
    try:
        return work_config.default_brain(WORK)
    except work_config.ConfigError as error:
        raise SystemExit(f"work config error: {error}") from None


def discover() -> list[Path]:
    """Brains present at the Work root, the default brain first."""
    try:
        return work_config.discover_brains(WORK)
    except work_config.ConfigError as error:
        raise SystemExit(f"work config error: {error}") from None


def shared_config() -> dict:
    default = default_brain()
    path = default / ".data/local-paths.json" if default else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}


def check_expected(brains: list[Path]) -> None:
    expected = shared_config().get("brains", [])
    missing = [name for name in expected if not (WORK / name).is_dir() or not work_config.is_brain(WORK / name)]
    if missing:
        raise SystemExit(
            "expected brain(s) missing: " + ", ".join(missing)
            + " — clone or restore them before processing transcripts"
        )
    if not brains:
        raise SystemExit(f"no brain found in {WORK}")


def load_transcripts(brains: list[Path]) -> dict[str, tuple[str, dict]]:
    """Union of transcript states, keyed by file name; refuses a file listed by two brains."""
    merged: dict[str, tuple[str, dict]] = {}
    conflicts: list[str] = []
    for brain in brains:
        state = brain / ".data/transcripts.json"
        if not state.is_file():
            continue
        for key, record in json.loads(state.read_text(encoding="utf-8")).items():
            if key in merged:
                conflicts.append(f"{key} ({merged[key][0]}, {brain.name})")
            else:
                merged[key] = (brain.name, record)
    if conflicts:
        raise SystemExit("transcript listed by several brains: " + "; ".join(conflicts))
    return merged


def transcripts_dir() -> Path:
    if "TRANSCRIPTS_DIR" in os.environ:
        return Path(os.environ["TRANSCRIPTS_DIR"])
    relative = shared_config().get("transcripts_dir")
    if not relative:
        default = default_brain()
        raise SystemExit(
            f"transcripts_dir missing from {default.name}/.data/local-paths.json" if default
            else "no default brain (several brains): set defaultBrain in work-config.local.json to read transcripts_dir"
        )
    return Path.home() / relative


def boundary(brain: Path) -> dict:
    """The brain's .data/brain.json, or {} when it has none."""
    path = brain / ".data/brain.json"
    if not path.is_file():
        return {}
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"{brain.name}/.data/brain.json is unreadable: {error}") from None
    return declared if isinstance(declared, dict) else {}


def one_line(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def cmd_brains(brains: list[Path]) -> int:
    """One line per brain: name, tracked transcripts, scope, description (tab-separated)."""
    for brain in brains:
        state = brain / ".data/transcripts.json"
        count = len(json.loads(state.read_text(encoding="utf-8"))) if state.is_file() else 0
        declared = boundary(brain)
        print(f"{brain.name}\t{count} transcript(s) tracked\t{one_line(declared.get('scope'))}\t{one_line(declared.get('description'))}")
    return 0


def cmd_transcripts(brains: list[Path], new: bool, where: str | None) -> int:
    merged = load_transcripts(brains)
    if where:
        if where not in merged:
            print(f"{where}\tnot tracked")
            return 1
        owner, record = merged[where]
        print(f"{where}\t{owner}\t{record.get('status', '?')}")
        return 0
    if new:
        folder = transcripts_dir()
        try:
            names = sorted(p.name for p in folder.iterdir() if p.suffix == ".txt")
        except (FileNotFoundError, NotADirectoryError):
            raise SystemExit(f"transcripts folder not found: {folder}") from None
        except PermissionError:
            raise SystemExit(
                f"Access denied to the transcripts folder: {folder}. "
                "Check the macOS permissions and that the synced folder (OneDrive, for example) is available, then run again."
            ) from None
        except OSError as error:
            raise SystemExit(f"cannot read the transcripts folder: {folder} ({error.strerror})") from None
        for name in names:
            if name not in merged:
                print(name)
        return 0
    for key in sorted(merged):
        owner, record = merged[key]
        print(f"{record.get('status', '?')}\t{owner}\t{key}")
    return 0


# --- map: where everything is ---------------------------------------------------------------------

STATE_KEYS = {" ": "open", "/": "in_progress", "w": "waiting", "x": "done"}
TIMELINE_ENTRY = re.compile(r"^[-*]\s+(\d{4}-\d{2}-\d{2})\s+[—–-]")
INBOX_SEPARATOR = re.compile(r"^-{3,}$")
INBOX_LOG = re.compile(r"^[-*]\s+\d{4}-\d{2}-\d{2}\s+[—–-]\s+triage\b", re.IGNORECASE)


def load_tools() -> tuple:
    """action.py and decision.py, loaded as decision.py does (one copy of action.py in sys.modules)."""
    here = Path(__file__).resolve().parent
    modules = []
    for file, name in (("action.py", "brain_action"), ("decision.py", "brain_decision")):
        module = sys.modules.get(name)
        if module is None:
            spec = importlib.util.spec_from_file_location(name, here / file)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        modules.append(module)
    return tuple(modules)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def timeline_entries(path: Path, whole: bool = False) -> list[dict]:
    """The `- YYYY-MM-DD — …` entries under the page's `## Timeline` (``whole``: of the whole file, for a journal).

    Each entry gives its `date`, its `line` number and its `text` (first line only, without the date)."""
    if not path.is_file():
        return []
    inside, found = whole, []
    for number, line in enumerate(read_lines(path), 1):
        if line.startswith("## ") and not whole:
            inside = line[3:].strip().lower() == "timeline"
        elif inside and (entry := TIMELINE_ENTRY.match(line)):
            found.append({"date": entry.group(1), "line": number, "text": line[entry.end():].strip()})
    return found


def last_timeline(page: Path) -> str | None:
    """Date of the most recent `- YYYY-MM-DD — …` entry under the page's `## Timeline`."""
    return max((entry["date"] for entry in timeline_entries(page)), default=None)


def inbox_lines(brain: Path) -> int:
    """Non-empty lines of inbox/inbox.md left to triage: below the first `---`, else below the title and quote."""
    path = brain / "inbox/inbox.md"
    if not path.is_file():
        return 0
    lines = [line.strip() for line in read_lines(path)]
    separator = next((index for index, line in enumerate(lines) if INBOX_SEPARATOR.match(line)), None)
    if separator is not None:
        lines = lines[separator + 1:]
    else:
        start = 0
        while start < len(lines) and (not lines[start] or lines[start].startswith(("#", ">"))):
            start += 1
        lines = lines[start:]
    return sum(1 for line in lines if line and not INBOX_LOG.match(line))


def people_pages(brain: Path) -> int:
    folder = brain / "people"
    if not folder.is_dir():
        return 0
    return sum(1 for page in folder.glob("*.md") if page.is_file() and not page.is_symlink() and page.name.lower() != "readme.md")


def register_prefix(register: Path, lines: list[str], ids: Counter, action) -> str | None:
    """The ID prefix of a register: the most frequent one among its actions (``ids``), else the one `action.py create` would use."""
    return ids.most_common(1)[0][0] if ids else action.fallback_prefix(register, lines)


def project_entry(brain: Path, name: str, register: Path, today: str, tools: tuple) -> dict:
    """One project (a folder holding state/actions.md) of the resolved `brain`, displayed under the brain's `name`."""
    action, decision = tools
    folder = register.parent.parent
    parts = register.relative_to(brain / "projects").parts[:-2]
    live = action.live_parts(parts)  # an archived project reads like a live one: its kind, its client
    kind = "client" if live[0] == "clients" else "internal"
    client = live[1] if kind == "client" and len(live) > 1 else None
    archived = action.in_archived_project(register, brain)
    base = f"{name}/projects/{'/'.join(parts)}"
    page = folder / f"{folder.name}.md"

    lines = read_lines(register)
    counts = {"open": 0, "in_progress": 0, "waiting": 0, "done": 0, "overdue": 0}
    prefixes: Counter = Counter()
    for number, line in enumerate(lines, 1):
        if not line.startswith("- ["):
            continue
        parsed = action.parse_action(line, register, brain, number)
        if parsed is None:
            continue
        if parsed["state"] in STATE_KEYS:
            counts[STATE_KEYS[parsed["state"]]] += 1
        if parsed["state"] in action.OPEN_STATES and parsed["due"] and parsed["due"] < today:
            counts["overdue"] += 1
        prefixes[parsed["id"].split("-")[0]] += 1
    prefix = register_prefix(register, lines, prefixes, action)

    decisions = folder / "state/decisions.md"
    proposed = None
    if decisions.is_file() and not decisions.is_symlink():
        proposed = sum(1 for item in decision.parse(read_lines(decisions)) if item.state == "proposed")

    return {
        "label": action.project_label(register, brain),
        "name": folder.name,
        "kind": kind,
        "client": client,
        "archived": archived,
        "page": f"{base}/{folder.name}.md" if page.is_file() else None,
        "register": f"{base}/state/actions.md",
        "prefix": prefix,
        "actions": counts,
        "decisions_proposed": proposed,
        "last_timeline": last_timeline(page),
    }


def brain_map(brain: Path, default: Path | None, scope: str, today: str, tools: tuple) -> dict:
    """One brain of the map; ``scope`` keeps the `live` projects, the `archived` ones or `all` of them."""
    name = brain.name
    declared = boundary(brain)
    brain = brain.resolve()
    action = tools[0]
    kept = project_registers(brain, action, scope)
    left_out = len(project_registers(brain, action, "all")) - len(kept)
    projects = [project_entry(brain, name, register, today, tools) for register in kept]
    projects.sort(key=lambda project: (project["archived"], project["name"]))

    clients: dict[tuple[str, bool], dict] = {}  # by (name, the whole client archived)
    root = brain / "projects/clients"

    def folders(shelf: Path) -> list[Path]:
        return [folder for folder in sorted(shelf.iterdir()) if folder.is_dir() and not folder.is_symlink()
                and not folder.name.startswith(".") and folder.name != "archive"] if shelf.is_dir() and not shelf.is_symlink() else []

    for shelf, archived in ((root, False), (root / "archive", True)):
        if archived and scope == "live":
            continue
        for folder in folders(shelf):
            index = folder / f"{folder.name}.md"
            clients[(folder.name, archived)] = {"name": folder.name, "archived": archived,
                                                "page": shown(name, brain, index) if index.is_file() else None, "projects": []}
    for project in projects:
        if project["client"] is not None:
            key = (project["client"], "/projects/clients/archive/" in project["register"])
            clients.setdefault(key, {"name": key[0], "archived": key[1], "page": None, "projects": []})["projects"].append(project)
    if scope == "archived":  # only the clients of the archived missions
        clients = {key: client for key, client in clients.items() if client["projects"]}
    return {
        "name": name,
        "default": default is not None and brain == default.resolve(),
        "scope": one_line(declared.get("scope")),
        "people": people_pages(brain),
        "inbox_lines": inbox_lines(brain),
        "clients": [clients[key] for key in sorted(clients)],
        "internal": [project for project in projects if project["client"] is None],
        "left_out": left_out,
    }


def render_map(data: dict) -> str:
    """The map as text: a header per brain, then one aligned line per project, grouped by client."""
    out: list[str] = []
    for brain in data["brains"]:
        tags = ", ".join(tag for tag in (brain["scope"], "default" if brain["default"] else "") if tag)
        inbox = f"inbox {brain['inbox_lines']} to triage" if brain["inbox_lines"] else "inbox empty"
        out.append(f"{brain['name']}" + (f" ({tags})" if tags else "") + f" — people {brain['people']} — {inbox}")
        groups = [(f"client {client['name']}" + (" [archived]" if client["archived"] else "") + f"  {client['page'] or '(no index page)'}",
                   client["projects"]) for client in brain["clients"]]
        if brain["internal"]:
            groups.append(("internal", brain["internal"]))
        shown = [project for _, projects in groups for project in projects]
        names = {id(project): project["name"] + (" [archived]" if project["archived"] else "") for project in shown}
        name_width = max(map(len, names.values()), default=0)
        prefix_width = max((len(project["prefix"] or "-") for project in shown), default=1)
        numbers = [value for project in shown for value in (*project["actions"].values(), project["decisions_proposed"]) if value is not None]
        digits = max((len(str(value)) for value in numbers), default=1)
        for title, projects in groups:
            out.append(f"  {title}")
            for project in projects:
                actions = project["actions"]
                proposed = "-" if project["decisions_proposed"] is None else str(project["decisions_proposed"])
                page = project["page"] or project["register"].removesuffix("/state/actions.md") + f"/{project['name']}.md (missing)"
                out.append(
                    f"    {names[id(project)]:<{name_width}}  {project['prefix'] or '-':<{prefix_width}}"
                    f"  open {actions['open']:>{digits}}  doing {actions['in_progress']:>{digits}}  wait {actions['waiting']:>{digits}}"
                    f"  done {actions['done']:>{digits}}  late {actions['overdue']:>{digits}}  dec {proposed:>{digits}}"
                    f"  last {project['last_timeline'] or '-':<10}  {page}"
                )
        if brain["left_out"]:
            what = "live" if data["scope"] == "archived" else "archived"
            how = "map, or map --all for both" if what == "live" else "map --archived, or map --all for both"
            out.append(f"  ({brain['left_out']} {what} project{'s' if brain['left_out'] > 1 else ''} not shown: {how})")
    out.append("")
    out.append("open/doing/wait/done: actions by state; late: unfinished actions past their due date; dec: proposed decisions; last: latest Timeline entry.")
    return "\n".join(out)


def cmd_map(brains: list[Path], only: str | None, as_json: bool, scope: str) -> int:
    brains = pick_brains(brains, only)
    tools = load_tools()
    today = tools[0].now().date().isoformat()
    default = default_brain()
    data = {"today": today, "scope": scope, "brains": [brain_map(brain, default, scope, today, tools) for brain in brains]}
    print(json.dumps(data, ensure_ascii=False, indent=2) if as_json else render_map(data))
    return 0

# --- brief, due, changes, find: context small enough to load at the start of a task ---------------

STATE_HEADINGS = ("current state",)
SUMMARY_HEADINGS = ("summary", "en bref", "context")
STATE_ORDER = {"/": 0, " ": 1, "w": 2}
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
EXCERPT = 120
COMBINING = re.compile("[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]")  # accents, once NFKD has split them off
# Typographic apostrophes, quotes and dashes, as they are typed on a keyboard.
PLAIN = str.maketrans({**dict.fromkeys("\u2018\u2019\u02bc\u201b", "'"), **dict.fromkeys("\u201c\u201d\u201e\u00ab\u00bb", '"'),
                       **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015", "-")})
TOKEN = re.compile(r"[a-z0-9]+")


def pick_brains(brains: list[Path], only: str | None) -> list[Path]:
    if only is None:
        return brains
    kept = [brain for brain in brains if brain.name == only]
    if not kept:
        raise SystemExit(f"unknown brain {only}: choose one of " + ", ".join(brain.name for brain in brains))
    return kept


def clip(text: str, limit: int = EXCERPT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def fold(text: str) -> str:
    """``text`` without case and accents, to compare what is typed with what the pages say (`É` is `e`).

    Typographic apostrophes, quotes and dashes become the plain ones, and a non-breaking space a space."""
    return COMBINING.sub("", unicodedata.normalize("NFKD", text).casefold()).translate(PLAIN)


def tokens(text: str) -> tuple[str, ...]:
    """The words of a name or of a title, folded and without punctuation."""
    return tuple(TOKEN.findall(fold(text)))


def find_folded(text: str, key: str) -> tuple[int, int] | None:
    """Where the folded ``key`` first occurs in ``text``, as a span of ``text`` itself; None when it does not."""
    folded, origin = [], []
    for index, char in enumerate(text):
        piece = fold(char)
        folded.append(piece)
        origin += [index] * len(piece)
    at = "".join(folded).find(key)
    return None if at < 0 or not key else (origin[at], origin[at + len(key) - 1] + 1)


def around(text: str, span: tuple[int, int] | None, limit: int) -> str:
    """At most ``limit`` characters of the one-line ``text``, centred on ``span`` (from its start when None), `…` where it is cut."""
    if len(text) <= limit:
        return text
    start, end = span or (0, 0)
    begin = max(0, min(start - max(limit - (end - start), 0) // 2, len(text) - limit))
    piece = text[begin:begin + limit]
    if begin:
        piece = "…" + piece[1:]
    if begin + limit < len(text):
        piece = piece[:-1] + "…"
    return piece


SCOPES = ("live", "archived", "all")  # which projects a command reads: the live ones (default), the archived ones, or both


def project_registers(brain: Path, action, scope: str = "live") -> list[Path]:
    """The registers of the projects of a resolved brain (a project is a folder holding state/actions.md), by ``scope``.

    An archived project is one moved whole into an `archive/` folder by `archive` (see `action.live_parts`)."""
    found = []
    for register in action.registers(brain):
        if len(register.relative_to(brain / "projects").parts) > 2 and (
                scope == "all" or action.in_archived_project(register, brain) == (scope == "archived")):
            found.append(register)
    return found


def each_project(brains: list[Path], action, scope: str = "live"):
    """(brain name, resolved brain, register) for every project of ``brains`` in ``scope`` (the live ones by default)."""
    for brain in brains:
        root = brain.resolve()
        for register in project_registers(root, action, scope):
            yield brain.name, root, register


def shown(name: str, brain: Path, path: Path) -> str:
    """A path of the resolved ``brain`` as written from the Work root, under the brain's ``name``."""
    return f"{name}/{path.relative_to(brain).as_posix()}"


def public_action(item: dict, today: str) -> dict:
    return {"id": item["id"], "state": item["state"], "due": item["due"], "owner": item["owner"], "title": item["title"],
            "late": item["state"] in STATE_ORDER and bool(item["due"]) and item["due"] < today}


def action_line(item: dict) -> str:
    return f"{item['id']} [{item['state']}] {item['due'] or '-':<10}  {clip(item['owner'] + ' — ' + item['title'])}"


def project_timeline(folder: Path, since: str | None = None, count: int | None = None) -> list[dict]:
    """Timeline entries of a project, newest first: its page, then its `journal/YYYY-MM.md` files.

    ``since`` keeps the entries dated from that day on; ``count`` stops reading older journals once it is reached."""
    found = [{**entry, "path": page} for page in [folder / f"{folder.name}.md"] for entry in timeline_entries(page)]
    journal = folder / "journal"
    months = sorted((path for path in journal.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}", path.stem) and not path.is_symlink()),
                    reverse=True) if journal.is_dir() and not journal.is_symlink() else []
    for path in months:
        if (since and path.stem < since[:7]) or (count is not None and len(found) >= count):
            break
        found += [{**entry, "path": path} for entry in timeline_entries(path, whole=True)]
    if since:
        found = [entry for entry in found if entry["date"] >= since]
    found.sort(key=lambda entry: entry["date"], reverse=True)
    return found if count is None else found[:count]


def project_decisions(folder: Path, decision) -> tuple[Path, list[str], list]:
    """The decision register of a project: its path, its lines and its parsed decisions (none when it is missing)."""
    path = folder / "state/decisions.md"
    if not path.is_file() or path.is_symlink():
        return path, [], []
    lines = read_lines(path)
    return path, lines, decision.parse(lines)


def state_section(page: Path) -> dict | None:
    """The page's `## Current state` section, else its first summary section (`fallback`); None when it has neither."""
    if not page.is_file():
        return None
    sections: dict[str, dict] = {}
    current = None
    for number, line in enumerate(read_lines(page), 1):
        if line.startswith("## "):
            current = {"heading": line[3:].strip(), "line": number, "lines": []}
            sections.setdefault(current["heading"].lower(), current)
        elif line.startswith("# "):
            current = None
        elif current is not None and line.strip():
            current["lines"].append(line.rstrip())
    for names, fallback in ((STATE_HEADINGS, False), (SUMMARY_HEADINGS, True)):
        for name in names:
            if sections.get(name, {}).get("lines"):
                return {**sections[name], "fallback": fallback}
    return None


def cut_words(lines: list[str], limit: int) -> tuple[list[str], int, int | None]:
    """The lines cut after ``limit`` words, the number of words left out and the index of the first line cut or left out.

    The line where the cut falls is kept in part, unless only its list or quote marker would be left of it."""
    kept, used, total = [], 0, sum(len(line.split()) for line in lines)
    for index, line in enumerate(lines):
        words = line.split()
        if used + len(words) > limit:
            head = words[:limit - used]
            if any(word.strip("-*+>#.0123456789") for word in head):
                kept.append(line[:len(line) - len(line.lstrip())] + " ".join(head) + " …")
                used = limit
            return kept, total - used, index
        kept.append(line)
        used += len(words)
    return kept, 0, None


def cap_words(lines: list[str], limit: int) -> tuple[list[str], int]:
    """The lines cut after ``limit`` words, and the number of words left out."""
    kept, more, _ = cut_words(lines, limit)
    return kept, more


def resolve_project(brains: list[Path], wanted: str, action, scope: str = "live", archived_hint: str = "",
                    live_hint: str = "drop --archived") -> tuple[str, Path, Path]:
    """(brain name, resolved brain, register) of the one project named ``wanted``, as `action.py --project` names it.

    ``scope`` says which projects may answer: an archived project named in the `live` scope is refused with
    ``archived_hint`` (how this command reads it) and the way to bring it back; a live one in the `archived` scope too.
    A live project wins over an archived one of the same name in the `all` scope."""
    known, matches = [], []
    for brain in brains:
        root = brain.resolve()
        registers = project_registers(root, action, "all")
        known += [(brain.name, root, register) for register in registers]
        try:
            matches += [(brain.name, root, register) for register in action.matching_registers(root, wanted) if register in registers]
        except action.ActionError as error:
            raise SystemExit(error.message) from None

    def listed(found: list) -> str:
        return "\n".join(f"  {name}: {action.project_label(register, root)}  ({shown(name, root, register.parent.parent)})"
                         for name, root, register in found)

    if not matches:  # the two short names `map` prints: the project folder name, then the register ID prefix
        bare = wanted.strip().strip("/")
        matches = [item for item in known if item[2].parent.parent.name == bare]
        if not matches and re.fullmatch(r"[A-Z][A-Z0-9]*", bare):
            def prefix(root: Path, register: Path) -> str | None:  # as `map` computes it, so what it prints resolves
                lines = read_lines(register)
                parsed = (action.parse_action(line, register, root, number) for number, line in enumerate(lines, 1) if line.startswith("- ["))
                return register_prefix(register, lines, Counter(item["id"].split("-")[0] for item in parsed if item), action)

            matches = [item for item in known if prefix(item[1], item[2]) == bare]
    live = [item for item in matches if not action.in_archived_project(item[2], item[1])]
    archived = [item for item in matches if action.in_archived_project(item[2], item[1])]
    if scope == "live" and archived and not live:
        name, root, register = archived[0]
        folder = shown(name, root, action.archived_root(register, root) or register.parent.parent)  # an archived client: the client
        raise SystemExit(f"project {wanted} is archived ({folder}), outside the context commands: "
                         + (f"{archived_hint}; " if archived_hint else "")
                         + f"`uv run tools/brain/brain-state.py unarchive {shlex.quote(folder)} --write` brings it back")
    if scope == "archived" and live and not archived:
        name, root, register = live[0]
        raise SystemExit(f"project {wanted} is not archived ({shown(name, root, register.parent.parent)}): {live_hint}")
    matches = archived if scope == "archived" else live or matches  # a client's missions share one prefix: the archived ones give way
    known = [item for item in known if scope == "all" or action.in_archived_project(item[2], item[1]) == (scope == "archived")]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise SystemExit(f"ambiguous project {wanted}: give --brain NAME or the folder of one of\n{listed(matches)}")
    words = [word for word in re.split(r"[\s/]+", wanted.lower()) if word]
    close = [item for item in known if any(word in shown(*item).lower() for word in words)]
    raise SystemExit(f"unknown project {wanted}: " + ("did you mean" if close else "the projects are") + f"\n{listed(close or known)}")


def register_ref(brain: Path, register: Path, action) -> str:
    """How `action.py --project` and `decision.py --project` name a register of ``brain`` without doubt: `client/mission`
    or the folder name, else the project folder from the brain."""
    folder = register.parent.parent
    parts = action.live_parts(folder.relative_to(brain / "projects").parts)
    short = f"{parts[1]}/{parts[3]}" if parts[0] == "clients" and len(parts) >= 4 else parts[-1]
    return short if action.matching_registers(brain, short) == [register] else folder.relative_to(brain).as_posix()


def project_ref(name: str, brain: Path, register: Path, brains: list[Path], action) -> str:
    """How `--project` of this script names a project without doubt among ``brains``: as `register_ref` does, else from the Work root."""
    short = register_ref(brain, register, action)
    found = [path for other in brains for path in action.matching_registers(other.resolve(), short)]
    return short if found == [register] else shown(name, brain, register.parent.parent)


def latest_index(folder: Path) -> Path | None:
    """The index of the latest month of the project's sources (`sources/YYYY-MM/index.md`), None when there is none."""
    sources = folder / "sources"
    if not sources.is_dir() or sources.is_symlink():
        return None
    found = sorted(path for path in sources.glob("*/index.md")
                   if re.fullmatch(r"\d{4}-\d{2}", path.parent.name) and path.is_file() and not path.is_symlink())
    return found[-1] if found else None


def load_next(name: str, brain: Path, register: Path, is_default: bool, action) -> list[dict]:
    """At most four commands that load one part of the project: the outline of its page, its open actions, its decisions
    and the latest index of its sources. `action.py` and `decision.py` get `--brain` outside the default brain, and
    `--archived` for an archived project (whose actions are all closed: they are listed whatever their state)."""
    folder = register.parent.parent
    page, decisions, index = folder / f"{folder.name}.md", folder / "state/decisions.md", latest_index(folder)
    ref = shlex.quote(register_ref(brain, register, action))
    option = "" if is_default else f"--brain {shlex.quote(name)} "
    archived = " --archived" if action.in_archived_project(register, brain) else ""
    found = []
    if page.is_file():
        found.append(("outline", f"uv run tools/brain/brain-state.py section {shlex.quote(shown(name, brain, page))}"))
    found.append(("actions", f"uv run tools/brain/action.py {option}list --project {ref} --state {'all' if archived else 'open'} --table{archived}"))
    if decisions.is_file() and not decisions.is_symlink():
        found.append(("decisions", f"uv run tools/brain/decision.py {option}list --project {ref} --table{archived}"))
    if index is not None:
        lines = read_lines(index)
        _, skip = front_matter(lines)
        top = next((item["line"] for item in headings_of(lines, skip)), 1)
        found.append(("sources", f"uv run tools/brain/brain-state.py section {shlex.quote(shown(name, brain, index))}:{top}"))
    return [{"what": what, "command": command} for what, command in found]


REPO_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def project_repos(name: str, brain: Path, register: Path, is_default: bool, action) -> dict | None:
    """The repositories that the brain's catalog `.data/client-repos.json` assigns to the project (its `project` field,
    named as for `brief`): their folder names, present or missing on this machine (a `.git` under `<Work>/<path>`), and the
    `client-repos.py` command that lists them. None when the catalog is absent or names none; never a path or a URL."""
    catalog = brain / ".data/client-repos.json"
    if not catalog.is_file() or catalog.is_symlink():
        return None
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
        entries = data.get("repositories") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError("no repositories list")
    except (OSError, ValueError) as error:
        print(f"warning: {shown(name, brain, catalog)} unreadable, repositories left out: {error}", file=sys.stderr)
        return None
    resolved: dict[str, bool] = {}
    labels: Counter = Counter()
    present: list[str] = []
    missing: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("project"), str):
            continue
        parts = entry["path"].split("/")
        if len(parts) != 3 or parts[0] != "repos" or not all(REPO_PART.fullmatch(part) and ".." not in part for part in parts[1:]):
            continue
        label = entry["project"]
        if label not in resolved:
            try:
                resolved[label] = register in action.matching_registers(brain, label)
            except action.ActionError:
                resolved[label] = False
        if not resolved[label]:
            continue
        labels[label] += 1
        (present if (WORK / entry["path"] / ".git").exists() else missing).append(parts[2])
    if not labels:
        return None
    prefix = "" if is_default else f"BRAIN_DIR={shlex.quote(name)} "
    command = f"{prefix}uv run tools/repos/client-repos.py list --project {shlex.quote(labels.most_common(1)[0][0])}"
    return {"count": len(present) + len(missing), "present": sorted(present), "missing": sorted(missing), "command": command}


def repos_line(repos: dict) -> str:
    names = f" ({', '.join(repos['present'])})" if repos["present"] else ""
    return (f"Repos: {repos['count']} in the catalog, {len(repos['present'])} present here{names}, {len(repos['missing'])} missing"
            f" — `{repos['command']}`")


def brief(name: str, brain: Path, register: Path, today: str, tools: tuple, words: int, limit: int, decisions_limit: int,
          is_default: bool = True) -> dict:
    action, decision = tools
    folder = register.parent.parent
    entry = project_entry(brain, name, register, today, tools)
    page = folder / f"{folder.name}.md"

    state = state_section(page)
    if state is not None:
        kept, more = cap_words(state["lines"], words)
        state = {"heading": state["heading"], "fallback": state["fallback"], "path": shown(name, brain, page), "line": state["line"],
                 "text": "\n".join(kept), "truncated_words": more}

    opened = [public_action(item, today) for item in action.load(register, brain) if item["state"] in action.OPEN_STATES]
    late = sorted((item for item in opened if item["late"]), key=lambda item: (item["due"], item["id"]))
    others = sorted((item for item in opened if not item["late"]),
                    key=lambda item: (STATE_ORDER[item["state"]], item["due"] or "9999", item["id"]))
    late_shown = late[:limit]
    others_shown = others[:limit - len(late_shown)]

    _, _, parsed = project_decisions(folder, decision)
    live = sorted((item for item in parsed if item.state in {"proposed", "accepted"}), key=lambda item: item.date, reverse=True)
    counts = {**entry["actions"], "decisions_proposed": sum(item.state == "proposed" for item in parsed),
              "decisions_accepted": sum(item.state == "accepted" for item in parsed)}

    return {
        "today": today,
        "brain": name,
        "project": entry["label"],
        "archived": entry["archived"],
        "state": state,
        "counts": counts,
        "actions": {"late": late_shown, "open": others_shown, "more": len(opened) - len(late_shown) - len(others_shown)},
        "decisions": {"items": [{"number": item.number, "state": item.state, "date": item.date, "title": item.title}
                                for item in live[:decisions_limit]], "more": max(len(live) - decisions_limit, 0)},
        "timeline": [{"date": item["date"], "text": item["text"], "path": shown(name, brain, item["path"]), "line": item["line"]}
                     for item in project_timeline(folder, count=5)],
        "repos": project_repos(name, brain, register, is_default, action),
        "load_next": load_next(name, brain, register, is_default, action),
    }


def render_brief(data: dict) -> str:
    out = [f"{data['brain']} — {data['project']}" + (" [archived]" if data["archived"] else "") + f" — today {data['today']}", ""]
    state = data["state"]
    if state is None:
        out.append("State: the project page has no `## Current state` or summary section")
    else:
        origin = f"`## {state['heading']}`" + (", the first summary section: the page has no `## Current state`" if state["fallback"] else "")
        out.append(f"State ({origin}) — {state['path']}:{state['line']}")
        out += [f"  {line}" for line in state["text"].splitlines()]
        if state["truncated_words"]:
            out.append(f"  (truncated, {state['truncated_words']} more words: {state['path']})")
    counts = data["counts"]
    out.append("")
    out.append(f"Actions: open {counts['open']}  doing {counts['in_progress']}  wait {counts['waiting']}  done {counts['done']}"
               f"  late {counts['overdue']} — decisions: proposed {counts['decisions_proposed']}  accepted {counts['decisions_accepted']}")
    actions = data["actions"]
    for title, items in (("Late", actions["late"]), ("Open, doing `/` first, then to do ` ` and waiting `w`", actions["open"])):
        if items:
            out += [f"{title}:"] + [f"  {action_line(item)}" for item in items]
    if actions["more"]:
        out.append(f"  +{actions['more']} more")
    decisions = data["decisions"]
    if decisions["items"]:
        out += ["", "Decisions, proposed and accepted, most recent first:"]
        out += [f"  no. {item['number']} [{item['state']}] {item['date'] or '-':<10}  {clip(item['title'])}" for item in decisions["items"]]
        if decisions["more"]:
            out.append(f"  +{decisions['more']} more")
    if data["timeline"]:
        out += ["", "Timeline, latest entries:"] + [f"  {item['date']}  {clip(item['text'], 200)}" for item in data["timeline"]]
    if data["repos"]:
        out += ["", repos_line(data["repos"])]
    width = max((len(item["what"]) for item in data["load_next"]), default=0)
    out += ["", "Load next, only the part the task needs:"] + [f"  {item['what']:<{width}}  {item['command']}" for item in data["load_next"]]
    return "\n".join(out)


def cmd_brief(brains: list[Path], args: argparse.Namespace) -> int:
    if min(args.words, args.limit, args.decisions) < 0:
        raise SystemExit("--words, --limit and --decisions must be zero or positive")
    tools = load_tools()
    today = tools[0].now().date().isoformat()
    name, brain, register = resolve_project(pick_brains(brains, args.brain), args.project, tools[0], "all" if args.archived else "live",
                                            f"`brief {shlex.quote(args.project)} --archived` reads it")
    default = default_brain()
    data = brief(name, brain, register, today, tools, args.words, args.limit, args.decisions,
                 default is not None and brain == default.resolve())
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render_brief(data))
    return 0


def cmd_due(brains: list[Path], only: str | None, days: int, as_json: bool) -> int:
    if days < 0:
        raise SystemExit("--days must be zero or positive")
    action = load_tools()[0]
    today = action.now().date()
    until = (today + timedelta(days=days)).isoformat()
    projects = []
    for name, brain, register in each_project(pick_brains(brains, only), action):
        found = [public_action(item, today.isoformat()) for item in action.load(register, brain)
                 if item["state"] in action.OPEN_STATES and item["due"] and item["due"] <= until]
        if found:
            found.sort(key=lambda item: (item["due"], item["id"]))  # late ones are the earliest
            projects.append({"brain": name, "project": action.project_label(register, brain),
                             "register": shown(name, brain, register), "actions": found})
    late = sum(item["late"] for project in projects for item in project["actions"])
    total = sum(len(project["actions"]) for project in projects)
    data = {"today": today.isoformat(), "days": days, "until": until, "late": late, "upcoming": total - late, "projects": projects}
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    for project in projects:
        print(f"{project['brain']} — {project['project']}  {project['register']}")
        for item in project["actions"]:
            print(f"  {'late' if item['late'] else 'due ':<4}  {action_line(item)}")
    print(f"{late} late, {total - late} due by {until} ({days} day(s) from {today.isoformat()})")
    return 0


CHANGES = 20  # events shown per project when `changes` covers every project


def since_day(value: str, today: date) -> str:
    value = value.strip()
    if found := re.fullmatch(r"(\d+)d", value):
        return (today - timedelta(days=int(found.group(1)))).isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise SystemExit(f"invalid --since {value}: expected YYYY-MM-DD or Nd (7d: the last seven days)") from None


def project_changes(name: str, brain: Path, register: Path, since: str, tools: tuple) -> list[dict]:
    """What the registers and the page of a project date from ``since`` on, newest first."""
    action, decision = tools
    folder = register.parent.parent
    events = [{"date": item["date"], "kind": "timeline", "text": item["text"], "path": shown(name, brain, item["path"]), "line": item["line"]}
              for item in project_timeline(folder, since=since)]
    archives = [path for path in sorted(register.parent.glob("actions-archive-*.md")) if path.is_file() and not path.is_symlink()]
    for path in [register, *archives]:
        for item in action.load(path, brain):
            text = f"{item['id']} [{item['state']}] {item['owner']} — {item['title']}"
            where = {"text": text, "path": shown(name, brain, path), "line": item["line"]}
            created = (item["created_at"] or item["created"])[:10]
            if created >= since:
                events.append({"date": created, "kind": "created", **where})
            if item["state"] not in action.OPEN_STATES and item["done"] >= since:
                events.append({"date": item["done"], "kind": "closed", **where})
    path, lines, parsed = project_decisions(folder, decision)
    for item in parsed:
        text = f"no. {item.number} [{item.status or item.state or '?'}] {item.title}"
        where = {"text": text, "path": shown(name, brain, path), "line": item.start + 1}
        if item.date >= since:
            events.append({"date": item.date, "kind": "decision", **where})
        fields = decision.fields_of(lines[item.start:item.end])
        settled = [day for key in ("accepted", "rejected", "superseded") for day in DAY.findall(fields.get(decision.FIELDS[key], ""))]
        if settled and max(settled) >= since and max(settled) != item.date:
            events.append({"date": max(settled), "kind": "settled", **where})
    events.sort(key=lambda event: event["date"], reverse=True)
    return events


def whole_days(events: list[dict], cap: int | None) -> tuple[list[dict], list[dict]]:
    """``events`` (newest first) cut after ``cap`` of them at a day boundary, and what is left: whole days only, the
    latest day always kept unless ``cap`` is 0. None keeps every event."""
    if cap is None or len(events) <= cap:
        return events, []
    kept = 0
    while kept < len(events) and cap:
        end = kept
        while end < len(events) and events[end]["date"] == events[kept]["date"]:
            end += 1
        if kept and end > cap:
            break
        kept = end
    return events[:kept], events[kept:]


def cmd_changes(brains: list[Path], only: str | None, since: str, project: str | None, limit: int | None, as_json: bool) -> int:
    if limit is not None and limit < 0:
        raise SystemExit("--limit must be zero or positive")
    tools = load_tools()
    action = tools[0]
    today = action.now().date()
    start = since_day(since, today)
    everywhere, brains = brains, pick_brains(brains, only)
    cap = limit if limit is not None or project else CHANGES  # one project: every event of the period
    projects = []
    total: Counter = Counter()
    hint = f"`find TERM --archived --project {shlex.quote(project)}` searches it" if project else ""
    for name, brain, register in [resolve_project(brains, project, action, archived_hint=hint)] if project else each_project(brains, action):
        events = project_changes(name, brain, register, start, tools)
        total.update(event["kind"] for event in events)
        if events:
            shown_events, rest = whole_days(events, cap)
            projects.append({"brain": name, "project": action.project_label(register, brain),
                             "ref": project_ref(name, brain, register, everywhere, action), "events": shown_events, "more": len(rest),
                             "more_dates": [rest[-1]["date"], rest[0]["date"]] if rest else None})
    data = {"today": today.isoformat(), "since": start, "projects": projects}
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    for item in projects:
        print(f"{item['brain']} — {item['project']}")
        for event in item["events"]:
            print(f"  {event['date']}  {event['kind']:<8}  {clip(event['text'])}")
        if item["more"]:
            first, last = item["more_dates"]
            days = f"on {first}" if first == last else f"from {first} to {last}"
            how = ("a higher --limit shows them" if project
                   else f"all of them: changes --since {shlex.quote(since.strip())} --project {shlex.quote(item['ref'])}")
            print(f"  +{item['more']} more {days}; {how}")
    print(f"since {start}: " + (", ".join(f"{total[kind]} {kind}" for kind in ("timeline", "created", "closed", "decision", "settled") if total[kind])
                                or "nothing dated in the registers and the timelines"))
    return 0


# --- find: every Markdown page of the brains, ranked ----------------------------------------------

KINDS = ("action", "decision", "page", "person", "workstream", "note", "journal", "source")
KIND_FOLDERS = (("sources", "source"), ("journal", "journal"), ("workstreams", "workstream"), ("notes", "note"), ("handoffs", "note"))
PATH_DAY = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")
HIT = 160
PER_FILE = 1  # hits shown per file by default: in a register, the block whose title matches comes first


def kind_of(parts: tuple[str, ...], project: int = 0) -> str:
    """The `find` kind of a Markdown file, from its path inside the brain.

    ``project`` is the number of leading parts that name its project folder (0: none), whose own name never sets the
    kind: a project called `notes` keeps its page a `page`."""
    name = parts[-1].lower()
    if parts[0] == "projects" and len(parts) > 3 and parts[-2] == "state":
        if name == "actions.md" or name.startswith("actions-archive-"):
            return "action"
        if name == "decisions.md":
            return "decision"
    for folder, kind in KIND_FOLDERS:
        if folder in parts[project:-1]:
            return kind
    if parts[0] == "people" and name != "readme.md":
        return "person"
    return "note" if parts[0] == "inbox" else "page"


LIVE, ARCHIVE, ARCHIVED_PROJECT = "live", "archive", "archived project"  # the tiers of the files `find` reads


def brain_files(brain: Path) -> list[tuple[str, str, tuple[str, ...], Path]]:
    """(kind, tier, path parts, file) for every Markdown file of the resolved ``brain`` that `find` reads.

    That is all of them but `skills/` and the hidden folders; a symbolic link is never followed. The tier is
    `archived project` for a file of an archived project or client (see `action.live_parts`),
    `archive` for the other files of an `archive/` folder (`people/archive/`…) and the action archives, else `live`."""
    action = load_tools()[0]
    found, projects = [], set()
    for folder, folders, files in os.walk(brain):
        base = Path(folder)
        parts = base.relative_to(brain).parts
        folders[:] = sorted(name for name in folders
                            if not name.startswith(".") and not (base / name).is_symlink() and (parts or name != "skills"))
        if parts[:1] == ("projects",) and (base / "state/actions.md").is_file():
            projects.add(parts)  # a project folder: the walk reaches it before what it holds
        project = max((len(other) for other in projects if parts[:len(other)] == other), default=0)
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".md") or (base / name).is_symlink():
                continue
            kind = kind_of((*parts, name), project)
            tier = (ARCHIVED_PROJECT if action.in_archived_project(Path(*parts, name), brain)
                    else ARCHIVE if "archive" in parts or (kind == "action" and name.lower() != "actions.md") else LIVE)
            found.append((kind, tier, (*parts, name), base / name))
    return found


def file_order(kind: str, brain: int, parts: tuple[str, ...]) -> tuple:
    """Sort key of a file among the hits: its kind, then most recent first for a journal or a source (date in the path), then its path."""
    day = 0
    if kind in {"journal", "source"} and (found := PATH_DAY.findall("/".join(parts))):
        year, month, monthday = found[-1]
        day = -(int(year) * 10000 + int(month) * 100 + int(monthday or 0))
    return KINDS.index(kind), day, brain, parts[0] != "projects", parts


def block_heads(kind: str, path: Path, brain: Path, lines: list[str], tools: tuple) -> dict[int, tuple[str, str | None, int]]:
    """For a register, what the lines of each action or decision are shown with, by line index.

    The value is the `ID [state]` or `no. N [state]` that opens the excerpt; for the first line of the block, its text
    without the Markdown of the register (None for the other lines: they are shown as written); and the index of
    the first line of the block, which names it."""
    action, decision = tools
    heads: dict[int, tuple[str, str | None, int]] = {}
    if kind == "action":
        index = 0
        while index < len(lines):
            parsed = action.parse_action(lines[index], path, brain, index + 1)
            if parsed is None:
                index += 1
                continue
            written = action.ACTION_RE.match(lines[index])
            head = f"{parsed['id']} [{parsed['state']}]"
            heads[index] = (head, " ".join(f"{written.group(3)} — {written.group(4)}".split()), index)
            last = action.last_detail(lines, index)
            heads.update((inner, (head, None, index)) for inner in range(index + 1, last + 1))
            index = last + 1
    elif kind == "decision":
        for item in decision.parse(lines):
            head = f"no. {item.number} [{item.status or item.state or '?'}]"
            heads[item.start] = (head, f"{item.title} ({item.date})" if item.date else item.title, item.start)
            heads.update((inner, (head, None, item.start)) for inner in range(item.start + 1, item.end))
    return heads


def file_hits(kind: str, name: str, brain: Path, path: Path, key: str, tools: tuple) -> list[dict]:
    """The lines of one file that hold the folded ``key``, each with an excerpt of 160 characters at most.

    In a register, one line per action or decision block: its first line when it matches, else its first matching
    sub-bullet. The blocks whose first line matches come first, then the other lines in line order."""
    lines = read_lines(path)
    if key not in " ".join(fold("\n".join(lines)).split()):
        return []
    heads = block_heads(kind, path, brain, lines, tools)
    where, titled, others, seen = shown(name, brain, path), [], [], set()
    for index, line in enumerate(lines):
        flat = " ".join(line.split())
        if key not in fold(flat):
            continue
        head, text, block = heads.get(index, ("", None, None))
        if block is not None:
            if block in seen:
                continue
            seen.add(block)
        if text is None:
            text = flat.removeprefix("- ") if head else flat
        room = HIT - len(head) - 1 if head else HIT
        hit = {"kind": kind, "brain": name, "path": where, "line": index + 1,
               "excerpt": (f"{head} " if head else "") + around(text, find_folded(text, key), room), "more_in_file": 0}
        (titled if block == index else others).append(hit)
    return titled + others


def kinds_from(value: str | None) -> tuple[str, ...]:
    """The kinds named by `--in` (a plural is accepted), all of them when the option is absent."""
    if value is None:
        return KINDS
    wanted = []
    for name in filter(None, re.split(r"[,\s]+", value.lower())):
        kind = "person" if name == "people" else name if name in KINDS else name.removesuffix("s")
        if kind not in KINDS:
            raise SystemExit(f"unknown kind {name}: choose among {', '.join(KINDS)}")
        wanted.append(kind)
    if not wanted:
        raise SystemExit(f"--in needs a kind: {', '.join(KINDS)}")
    return tuple(kind for kind in KINDS if kind in wanted)


def cmd_find(brains: list[Path], only: str | None, term: str, limit: int, per_file: int, kinds_wanted: str | None,
             scope: str, as_json: bool, project: str | None = None) -> int:
    """``scope``: `live` reads the live projects and the rest of the brains, then the archives when nothing matches,
    never the archived projects; `archived` reads the archived projects only; `all` reads everything."""
    typed = " ".join(term.split())
    key = fold(typed)
    if not key:
        raise SystemExit("empty search term")
    if limit < 0 or per_file < 0:
        raise SystemExit("--limit and --per-file must be zero or positive")
    kinds = kinds_from(kinds_wanted)
    tools = load_tools()
    action = tools[0]
    picked = pick_brains(brains, only)
    folder_scope, files, left_out_projects = None, [], 0
    if project:  # one project folder: its page, registers, sources, journal, notes and workstreams
        name, root, register = resolve_project(picked, project, action, scope,
                                               f"`find {shlex.quote(typed)} --archived --project {shlex.quote(project)}` searches it")
        folder = register.parent.parent
        folder_scope = shown(name, root, folder)
        files = [(file_order(kind, 0, parts), name, root, kind, tier, path)
                 for kind, tier, parts, path in brain_files(root) if kind in kinds and path.is_relative_to(folder)]
    for index, brain in enumerate([] if project else picked):
        root = brain.resolve()
        files += [(file_order(kind, index, parts), brain.name, root, kind, tier, path)
                  for kind, tier, parts, path in brain_files(root) if kind in kinds]
        if scope == "live":
            left_out_projects += len(project_registers(root, action, "archived"))
    files.sort(key=lambda item: item[0])

    def search(batch: list[tuple]) -> tuple[list[dict], Counter]:
        kept, totals = [], Counter()
        for _, name, root, kind, _, path in batch:
            hits = file_hits(kind, name, root, path, key, tools)
            totals[kind] += len(hits)
            first = hits[:per_file] if per_file else hits
            if len(hits) > len(first):
                first[-1]["more_in_file"] = len(hits) - len(first)
            kept += first
        return kept, totals

    wanted = {"live": {LIVE}, "archived": {ARCHIVED_PROJECT}, "all": {LIVE, ARCHIVE, ARCHIVED_PROJECT}}[scope]
    batch = [item for item in files if item[4] in wanted]
    kept, totals = search(batch)
    read, archives_only = len(batch), False
    if not kept and scope == "live":  # so that "no match" also holds for the archives of the live projects
        batch = [item for item in files if item[4] == ARCHIVE]
        kept, totals = search(batch)
        read, archives_only = read + len(batch), bool(kept)

    visible = kept[:limit]
    left = Counter(totals)
    for hit in visible:
        left[hit["kind"]] -= 1 + hit["more_in_file"]
    more = {kind: left[kind] for kind in sorted(left, key=lambda kind: (-left[kind], KINDS.index(kind))) if left[kind]}
    data = {"term": typed, "scope": scope, "total": sum(totals.values()), "kinds": {kind: totals[kind] for kind in KINDS if totals[kind]},
            "hits": visible, "more": {"total": sum(more.values()), "kinds": more},
            "brains": [brain.name for brain in picked] if folder_scope is None else [folder_scope.split("/")[0]], "project": folder_scope,
            "files": read, "archives_only": archives_only, "archived_projects_left_out": left_out_projects}
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if archives_only:
        print(f'nothing in the live pages for "{typed}"; in the archives:')
    current = None
    for hit in visible:  # each file once, then its hits
        if hit["path"] != current:
            print(f"{hit['kind']:<10}  {hit['path']}")
            current = hit["path"]
        print(f"  :{hit['line']}  {hit['excerpt']}" + (f"  (+{hit['more_in_file']} in this file)" if hit["more_in_file"] else ""))
    if more:
        print(f"+{data['more']['total']} more: " + ", ".join(f"{kind} {count}" for kind, count in more.items())
              + " — narrow with --in, " + ("--per-file" if folder_scope else "--project") + " or --limit")
    if not data["total"]:
        only_kinds = set(kinds) != set(KINDS)
        projects = (f"{left_out_projects} archived project" + (f"s (--archived searches them)" if left_out_projects > 1
                                                               else " (--archived searches it)"))
        left_out = ((["the other kinds (drop --in)"] if only_kinds else []) + (["the rest of the brains (drop --project)"] if folder_scope else [])
                    + ([projects] if left_out_projects else []) + (["the live projects (--all searches everything)"] if scope == "archived" and not folder_scope else [])
                    + ["skills/ and hidden folders"])
        where = folder_scope or ", ".join(data["brains"])
        read_in = {"live": f"{where}, archives included", "archived": f"the archived projects of {where}",
                   "all": f"{where}, archives and archived projects included"}[scope]
        if folder_scope and scope != "live":
            read_in = f"{where}, archives included"
        print(f'no match for "{typed}"' + (f" in {', '.join(kinds)}" if only_kinds else "")
              + f": {read} Markdown file(s) read in {read_in}; left out: {', '.join(left_out)}")
    return 0


# --- section: the outline of a page, or one of its sections ---------------------------------------

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FRONT_KEY = re.compile(r"^([A-Za-z_][\w.-]*)[ \t]*:[ \t]*(.*)$")
SUMMARY_TITLES = ("summary", "resume", "en bref", "current state", "etat actuel")  # folded; what `summary` stands for, in this order
VALUE, TITLE = 100, 80  # characters of a front-matter value and of a title in the outline
WINDOW, SECTION = 150, 400  # words printed around FILE:LINE, and of a section named by its heading


def front_matter(lines: list[str]) -> tuple[dict[str, str], int]:
    """The `key: value` pairs of the `---` block that opens a page, and the number of lines it takes (0: none).

    A value written on several lines (block list, folded text) is joined on one line."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    end = next((index for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."}), None)
    if end is None:
        return {}, 0
    found: dict[str, str] = {}
    key = None
    for line in lines[1:end]:
        pair = FRONT_KEY.match(line)
        if pair:
            key = pair.group(1)
            found[key] = pair.group(2).strip()
        elif key and line.strip():
            found[key] = f"{found[key]} {line.strip()}".strip()
    return found, end + 1


def headings_of(lines: list[str], skip: int = 0) -> list[dict]:
    """The headings of a Markdown page below its first ``skip`` lines, code fences left out.

    Each gives its `level`, `title` and `line`, the last line of its section (`end`: up to the next heading of the
    same or a higher level) and the `words` of that section, title excluded."""
    found, fence = [], ""
    for index in range(skip, len(lines)):
        mark = FENCE.match(lines[index])
        if mark and (not fence or (mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence))):
            fence = "" if fence else mark.group(1)
        elif not fence and (heading := HEADING.match(lines[index])):
            found.append({"level": len(heading.group(1)), "title": heading.group(2).strip(), "line": index + 1})
    for position, item in enumerate(found):
        following = next((other["line"] for other in found[position + 1:] if other["level"] <= item["level"]), len(lines) + 1)
        item["end"] = following - 1
        item["words"] = sum(len(line.split()) for line in lines[item["line"]:item["end"]])
    return found


def brain_file(brains: list[Path], given: str) -> tuple[str, Path, Path]:
    """(brain name, resolved brain, file) for a Markdown file named from the Work root, from a brain or by its full path.

    Only a file that resolves inside one of ``brains`` is accepted: a path that leaves them, through `..` or a
    symbolic link, is refused."""
    path = Path(given).expanduser()
    candidates = [path] if path.is_absolute() else [WORK / path, *(brain / path for brain in brains)]
    inside, outside = [], False
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_file():
            continue
        homes = [(brain.name, brain.resolve()) for brain in brains if resolved.is_relative_to(brain.resolve())]
        outside = outside or not homes
        inside += [(name, root, resolved) for name, root in homes if (name, root, resolved) not in inside]
    if len(inside) > 1:
        raise SystemExit(f"several files are named {given}: give the path from the Work root\n"
                         + "\n".join(f"  {shown(*item)}" for item in inside))
    if not inside:
        names = ", ".join(brain.name for brain in brains)
        raise SystemExit(f"{given} is outside {names}: only the files of a brain are read" if outside
                         else f"no file {given} in {names}: give the path that `find` or `brief` prints, from the Work root")
    if inside[0][2].suffix.lower() != ".md":
        raise SystemExit(f"{given} is not a Markdown file")
    return inside[0]


def match_heading(found: list[dict], wanted: str) -> list[dict]:
    """The headings that ``wanted`` names: the exact title, else the titles it starts, else those it is part of.

    Case and accents do not count. `summary` stands for the first abstract of the page: Summary, Résumé, En bref,
    Current state or État actuel, in that order."""
    titles = [(" ".join(fold(item["title"]).split()), item) for item in found]
    key = " ".join(fold(wanted).split())
    tests = (str.__eq__, str.startswith, str.__contains__)
    if key == "summary":
        for test in tests:
            for name in SUMMARY_TITLES:
                if hits := [item for title, item in titles if test(title, name)]:
                    return hits[:1]
        return []
    for test in tests:
        if hits := [item for title, item in titles if test(title, key)]:
            return hits
    return []


def cut_section(lines: list[str], first: int, last: int, limit: int, target: int | None = None) -> dict:
    """The lines ``first`` to ``last`` (indexes, ``last`` excluded) without the blank lines around them, cut after ``limit`` words.

    When they do not fit and ``target`` is one of them, the window keeps the top only when the target line ends in its
    first two thirds; otherwise it starts a few lines above the target (a third of the words at most), so that the
    line has words on both sides. `skipped_words` counts what is left above."""
    while first < last and not lines[first].strip():
        first += 1
    while last > first and not lines[last - 1].strip():
        last -= 1

    def count(start: int, stop: int) -> int:
        return sum(len(line.split()) for line in lines[start:stop])

    begin = first
    if target is not None and first < target < last and count(first, last) > limit and count(first, target + 1) > limit - limit // 3:
        begin, above = target, 0
        while begin > first and above + len(lines[begin - 1].split()) <= limit // 3:
            begin -= 1
            above += len(lines[begin].split())
        while begin < target and not lines[begin].strip():
            begin += 1
    kept, more, cut = cut_words([line.rstrip() for line in lines[begin:last]], limit)
    return {"text": "\n".join(kept), "from_line": begin + 1, "skipped_words": count(first, begin), "truncated_words": more,
            "truncated_at": None if cut is None else begin + cut + 1}


def heading_line(item: dict, low: int = 1) -> str:
    return f"{item['line']:>5}  {'  ' * (item['level'] - low)}{'#' * item['level']} {clip(item['title'], TITLE)}  ({item['words']} words)"


def cmd_section(brains: list[Path], only: str | None, target: str, heading: list[str], words: int | None, as_json: bool) -> int:
    given, _, tail = target.rpartition(":")
    file, line = (given, int(tail)) if given and tail.isdigit() else (target, None)
    if words is None:
        words = WINDOW if line is not None else SECTION
    if words < 0:
        raise SystemExit("--words must be zero or positive")
    wanted = " ".join(" ".join(heading).split())
    if line is not None and wanted:
        raise SystemExit("give a line (FILE:LINE) or a heading, not both")
    name, root, path = brain_file(pick_brains(brains, only), file)
    where = shown(name, root, path)
    lines = read_lines(path)
    front, skip = front_matter(lines)
    found = headings_of(lines, skip)
    low = min((item["level"] for item in found), default=1)
    listed = "\n".join(heading_line(item, low) for item in found) or "  (no heading)"

    if line is None and not wanted:
        total = sum(len(text.split()) for text in lines)
        data = {"path": where, "words": total, "front_matter": front,
                "headings": [{key: item[key] for key in ("level", "title", "line", "words")} for item in found]}
        if as_json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        print(where)
        if front:
            print("front matter:")
            for key, value in front.items():
                print(f"  {key}: {clip(value, VALUE)}")
        print("headings (line, title, words of the section):")
        print(listed)
        print(f"total: {total} words")
        return 0

    if line is not None:
        if not 1 <= line <= len(lines):
            raise SystemExit(f"{where} has {len(lines)} lines: no line {line}")
        item = next((item for item in reversed(found) if item["line"] <= line), None)
        if item is None:  # above the first heading: the top of the page, front matter included
            top = (found[0]["line"] if found else len(lines) + 1) - 1
            item = {"level": 0, "title": "", "line": 1, "end": top, "words": sum(len(text.split()) for text in lines[:top])}
    else:
        hits = match_heading(found, wanted)
        if len(hits) > 1:
            raise SystemExit(f"several headings of {where} match {wanted}: give more of the title, or its line ({where}:LINE)\n"
                             + "\n".join(heading_line(hit, low) for hit in hits))
        if not hits:
            raise SystemExit(f"no heading of {where} matches {wanted}; its headings (line, title, words of the section):\n{listed}")
        item = hits[0]

    body = cut_section(lines, item["line"] if item["level"] else 0, item["end"], words, None if line is None else line - 1)
    data = {"path": where, "line": item["line"], "level": item["level"], "heading": item["title"], "words": item["words"], **body}
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    title = f"{'#' * item['level']} {item['title']}" if item["level"] else "(top of the page, above its first heading)"
    print(f"{where}:{item['line']}  {title}  ({item['words']} words)")
    if body["skipped_words"]:
        print(f"(… {body['skipped_words']} words above; from line {body['from_line']})")
    if body["text"]:
        print(body["text"])
    if body["truncated_words"]:
        print(f"(truncated, {body['truncated_words']} more words: {where}:{body['truncated_at']})")
    return 0


# --- person: who someone is and what they carry ----------------------------------------------------

ROLE_TITLES = ("role and scope", "role et perimetre", "context", "contexte")  # folded: the section that says who the person is
OWNER_SPLIT = re.compile(r"[/,;+&()]|\b(?:then|puis|and|et|with|avec)\b", re.IGNORECASE)
FLOW_ITEM = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)'|([^,]+))""")


def flow_list(value: str) -> list[str]:
    """The items of a YAML list written on one line (`[a, "b c"]`), or of a block list that `front_matter` joined (`- a - b`)."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        parts = ["".join(groups) for groups in FLOW_ITEM.findall(value[1:-1])]
    else:
        parts = re.split(r"(?:^|\s)-\s+", value) if value.startswith("- ") else [value]
    return [item for part in parts if (item := part.strip().strip("\"'").strip())]


def people_of(brains: list[Path]) -> list[dict]:
    """One entry per people page of ``brains``: `people/*.md`, then `people/archive/*.md` flagged `archived`.

    `tokens` are the words of the name, `slug` those of the file name, `alias_tokens` those of each alias."""
    found = []
    for brain in brains:
        root = brain.resolve()
        for folder, archived in ((root / "people", False), (root / "people/archive", True)):
            if not folder.is_dir() or folder.is_symlink():
                continue
            for path in sorted(folder.glob("*.md")):
                if path.is_symlink() or not path.is_file() or path.name.lower() == "readme.md":
                    continue
                lines = read_lines(path)
                front, skip = front_matter(lines)
                title = next((line[2:].strip() for line in lines[skip:] if line.startswith("# ")), "")
                name = front.get("name", "").strip("\"' ") or title or path.stem.replace("-", " ")
                aliases = flow_list(front.get("aliases", ""))
                found.append({"brain": brain.name, "root": root, "path": path, "archived": archived, "lines": lines, "front": front,
                              "skip": skip, "name": name, "aliases": aliases, "tokens": tokens(name), "slug": tokens(path.stem),
                              "alias_tokens": {tokens(alias) for alias in aliases} - {()}, "owner_of": []})
    return found


def owners_of(brains: list[Path], pages: list[dict], action) -> list[dict]:
    """The owners of ``brains`` (`BRAIN_OWNER`, else `owner` in `.data/doctor.json`) who have no people page, as one more
    person each: the registers name them too, mostly by a first name that a people page may also bear.

    `path` is the profile `me/about-me.md` of the first brain they own; `owner_of` names their brains."""
    found: dict[tuple, dict] = {}
    for brain in brains:
        root = brain.resolve()
        try:
            name = action.board_owner(root)
        except (SystemExit, OSError, ValueError, AttributeError):  # no owner declared, or an unreadable doctor.json
            continue
        key = tokens(name)
        if key and not any(page["tokens"] == key and not page["archived"] for page in pages):
            found.setdefault(key, {"brain": brain.name, "root": root, "path": root / "me/about-me.md", "archived": False, "lines": [],
                                   "front": {}, "skip": 0, "name": name, "aliases": [], "tokens": key, "slug": key,
                                   "alias_tokens": set(), "owner_of": []})["owner_of"].append(brain.name)
    return list(found.values())


def resolve_person(pages: list[dict], wanted: str) -> dict:
    """The one people page named ``wanted``: its slug or full name, else words of its name, of its slug or of one alias."""
    key = tokens(wanted)
    if not key:
        raise SystemExit("empty name")

    def listed(found: list[dict]) -> str:
        return "\n".join(f"  {page['brain']}: {page['name']}  ("
                         + (f"owner of {', '.join(page['owner_of'])}, without a people page" if page["owner_of"]
                            else shown(page["brain"], page["root"], page["path"])) + ")" + (" [archived]" if page["archived"] else "")
                         for page in found)

    for pool in ([page for page in pages if not page["archived"]], [page for page in pages if page["archived"]]):
        exact = [page for page in pool if key in (page["tokens"], page["slug"])]
        loose = exact if len(exact) == 1 else [page for page in pool if any(set(key) <= set(naming) for naming in
                                                                              (page["tokens"], page["slug"], *page["alias_tokens"]))]
        if len(loose) == 1:
            return loose[0]
        if loose:
            raise SystemExit(f"several people are named {wanted}: give the full name, or --brain NAME\n{listed(loose)}")

    namings: dict[str, dict] = {}
    for page in pages:
        for naming in (page["tokens"], page["slug"], *sorted(page["alias_tokens"])):
            namings.setdefault(" ".join(naming), page)
    close = [namings[naming] for naming in difflib.get_close_matches(" ".join(key), list(namings), n=5, cutoff=0.6)]
    close += [page for page in pages if any(mine.startswith(word) or word.startswith(mine) for word in key if len(word) > 2
                                            for naming in (page["tokens"], page["slug"], *page["alias_tokens"])
                                            for mine in naming if len(mine) > 2)]
    close = [page for index, page in enumerate(close) if all(page is not other for other in close[:index])][:5]
    hint = f'for an owner without a page: uv run tools/brain/action.py list --owner "{wanted}" --table'
    count = sum(not page["owner_of"] for page in pages)
    raise SystemExit(f"unknown person {wanted}: " + (f"the closest names are\n{listed(close)}\n" if close
                                                    else f"none of the {count} people pages has a close name; ") + hint)


def identity(page: dict) -> list[tuple[int, str]]:
    """The identity part of a people page as (line number, text): name, role, organization, aliases and missions of the
    front matter (line 0: not written as such), the lines under the title, then the section that says who the person is."""
    if page["owner_of"]:
        return [(0, f"{page['name']} — owner of {', '.join(page['owner_of'])}, without a people page")]
    front, lines, skip = page["front"], page["lines"], page["skip"]
    out = [(0, " — ".join(part for part in (page["name"], front.get("role", "").strip("\"' "),
                                           front.get("organization", "").strip("\"' ")) if part))]
    out += [(0, f"{key}: {', '.join(items)}") for key in ("aliases", "missions") if (items := flow_list(front.get(key, "")))]
    title = next((index for index in range(skip, len(lines)) if lines[index].startswith("# ")), None)
    start = skip if title is None else title + 1
    stop = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))
    out += [(index + 1, lines[index].rstrip()) for index in range(start, stop) if lines[index].strip()]
    role = next((item for item in headings_of(lines, skip) if item["level"] == 2 and " ".join(fold(item["title"]).split()) in ROLE_TITLES), None)
    if role:
        out += [(index + 1, lines[index].rstrip()) for index in range(role["line"] - 1, role["end"]) if lines[index].strip()]
    return out


def claimants(part: tuple[str, ...], pool: list[dict]) -> list[dict]:
    """The people an owner name may stand for: the one with that full name, else those it is the first name or an alias of."""
    full = [page for page in pool if page["tokens"] == part]
    return full or [page for page in pool
                    if (len(part) < len(page["tokens"]) and page["tokens"][:len(part)] == part) or part in page["alias_tokens"]]


def carried(page: dict, pages: list[dict], brains: list[Path], action, today: str) -> tuple[list[dict], dict[tuple, list[dict]]]:
    """The open actions ``page`` carries, and those whose owner may be someone else, by (owner as written, people it may stand for).

    An owner names one person or several (`A / B`, `A, then B`); each name is looked up among the people of the
    register's brain (its people pages and its owner), then of the other brains. The action is carried when one of
    its names stands for ``page`` alone."""
    live = [other for other in pages if not other["archived"] or other is page]
    sure, unsure = [], {}
    for name, root, register in each_project(brains, action):
        local = [other for other in live if name in (other["owner_of"] or [other["brain"]])]
        for item in action.load(register, root):
            if item["state"] not in action.OPEN_STATES:
                continue
            mine, doubt = False, None
            for written in OWNER_SPLIT.split(item["owner"]):
                part = tokens(written)
                who = (claimants(part, local) or claimants(part, live)) if part else []
                if not any(other is page for other in who):
                    continue
                if len(who) == 1:
                    mine = True
                elif doubt is None:
                    doubt = (" ".join(written.split()), tuple(other["name"] for other in who))
            entry = {**public_action(item, today), "project": item["project"]}
            if mine:
                sure.append(entry)
            elif doubt:
                unsure.setdefault(doubt, []).append(entry)
    return sure, unsure


def by_urgency(items: list[dict]) -> list[dict]:
    """Late actions first, by due date; then in progress, to do and waiting, by due date."""
    return sorted(items, key=lambda item: (0, 0, item["due"], item["id"]) if item["late"]
                  else (1, STATE_ORDER[item["state"]], item["due"] or "9999", item["id"]))


def person_line(item: dict, name: tuple[str, ...]) -> str:
    shared = "" if tokens(item["owner"]) == name else f", owner: {item['owner']}"
    return (f"  {'late' if item['late'] else '    '}  {item['id']} [{item['state']}] {item['due'] or '-':<10}  "
            f"{clip(item['title'])}  ({item['project']}{shared})")


def cmd_person(brains: list[Path], only: str | None, wanted: str, words: int, limit: int, as_json: bool) -> int:
    if min(words, limit) < 0:
        raise SystemExit("--words and --limit must be zero or positive")
    action = load_tools()[0]
    today = action.now().date().isoformat()
    picked = pick_brains(brains, only)
    pages = people_of(picked)
    pages += owners_of(picked, pages, action)
    page = resolve_person(pages, " ".join(wanted.split()))
    where = shown(page["brain"], page["root"], page["path"]) if page["path"].is_file() else None
    parts = identity(page)
    kept, more, cut = cut_words([text for _, text in parts], words)
    cut_line = parts[cut][0] if cut is not None else None
    sure, unsure = carried(page, pages, picked, action, today)
    sure = by_urgency(sure)
    front = page["front"]
    data = {
        "today": today,
        "brain": page["brain"],
        "path": where,
        "archived": page["archived"],
        "owner_of": page["owner_of"],
        "name": page["name"],
        "role": front.get("role", "").strip("\"' "),
        "organization": front.get("organization", "").strip("\"' "),
        "aliases": page["aliases"],
        "missions": flow_list(front.get("missions", "")),
        "identity": {"text": "\n".join(kept), "truncated_words": more, "truncated_at": cut_line or None},
        "actions": {"total": len(sure), "late": sum(item["late"] for item in sure), "items": sure[:limit],
                    "more": max(len(sure) - limit, 0)},
        "ambiguous": [{"owner": owner, "between": list(names), "total": len(items), "items": by_urgency(items)[:limit],
                       "more": max(len(items) - limit, 0)} for (owner, names), items in unsure.items()],
    }
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(data["identity"]["text"])
    if more:
        print(f"(truncated, {more} more words" + (f": {where}" + (f":{cut_line}" if cut_line else "") if where else "") + ")")
    print()
    actions = data["actions"]
    print(f"Open actions carried: {actions['total'] or 'none'}" + (f", {actions['late']} late" if actions["late"] else "")
          + f" (today {today})")
    for item in actions["items"]:
        print(person_line(item, page["tokens"]))
    if actions["more"]:
        print(f"  +{actions['more']} more")
    for group in data["ambiguous"]:
        print(f"Owner \"{group['owner']}\" is ambiguous between {' and '.join(group['between'])}: "
              f"{group['total']} open action(s), not counted above")
        for item in group["items"]:
            print(person_line(item, page["tokens"]))
        if group["more"]:
            print(f"  +{group['more']} more")
    print(f"Page: {where or 'none'}" + (" (archived)" if page["archived"] else " (the owner's profile)" if where and page["owner_of"] else ""))
    return 0


# --- archive, unarchive: a finished project leaves the context whole, and comes back ---------------

MD_LINK = re.compile(r"\[(?:[^\[\]]|\[\[[^\]]*\]\])*\]\(([^)\s]+)\)")  # a Markdown link, as tools/brain/check-links.py reads it
CODE_FENCE = re.compile(r"```.*?```", re.S)
CODE_SPAN = re.compile(r"`[^`\n]*`")
NOT_RELATIVE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|/|<)", re.I)  # a URL, an anchor, a root path: never rewritten
LINK_COUNTS = re.compile(r"^(files|md links|wikilinks|dead \(md\)|dead \(wiki\)|cross-brain|unverified local links)\s*:\s*(\d+)")


LIVE_SHAPES = {  # what `archive` moves, and where: the `archive/` folder at the level of what it holds
    ("clients", "*", "missions", "*"): ("clients", 1, "missions", "archive", 3),  # a client mission
    ("internal", "*"): ("internal", "archive", 1),  # an internal project
    ("clients", "*"): ("clients", "archive", 1),  # a whole client, with all its missions
}
EARLIER_SHAPES = {  # the earlier archive places, which `archive` files again in the new ones and `unarchive` brings back
    ("archive", "*"): (("internal", "archive", 1), ("internal", 1)),
    ("clients", "*", "archive", "*"): (("clients", 1, "missions", "archive", 3), ("clients", 1, "missions", 3)),
}


def shape_of(parts: tuple[str, ...], shapes) -> tuple | None:
    """The shape of ``shapes`` that ``parts`` (below `projects/`) has: literal names, `*` for any name but `archive`."""
    return next((shape for shape in shapes if len(shape) == len(parts) and all(
        part != "archive" if want == "*" else part == want for want, part in zip(shape, parts))), None)


def placed(parts: tuple[str, ...], pattern: tuple) -> tuple[str, ...]:
    """``pattern`` with each number replaced by that part of ``parts``."""
    return tuple(parts[item] if isinstance(item, int) else item for item in pattern)


def archive_destination(brain: Path, folder: Path, back: bool) -> tuple[Path, str]:
    """Where ``folder`` goes, and what it is (`mission`, `internal`, `client`). `archive` puts a client mission in
    `clients/<c>/missions/archive/<m>`, an internal project in `internal/archive/<p>`, a whole client in `clients/archive/<c>`,
    and files a project of an earlier archive place (`archive/<p>`, `clients/<c>/archive/<m>`) in the new one; `unarchive`
    brings each back where it was. One level deeper: the links inside that point out are rewritten too."""
    parts = folder.relative_to(brain / "projects").parts
    kinds = {4: "mission", 2: "internal"}
    if not back:
        if (shape := shape_of(parts, LIVE_SHAPES)) is not None:
            return brain / "projects" / Path(*placed(parts, LIVE_SHAPES[shape])), "client" if shape == ("clients", "*") else kinds[len(shape)]
        if (shape := shape_of(parts, EARLIER_SHAPES)) is not None:
            return brain / "projects" / Path(*placed(parts, EARLIER_SHAPES[shape][0])), kinds[len(shape)]
        what = "already archived" if action_tool().in_archived_project(folder, brain) else (
            "not a client mission (projects/clients/<client>/missions/<mission>/), an internal project (projects/internal/<project>/) "
            "or a client (projects/clients/<client>/)")
        raise SystemExit(f"{folder.relative_to(brain).as_posix()} is {what}: nothing to archive")
    for shape, pattern in LIVE_SHAPES.items():
        archived = tuple(item if isinstance(item, str) else "*" for item in pattern)
        if shape_of(parts, {archived: None}) is not None:
            names = {position: part for position, part in zip(pattern, parts) if isinstance(position, int)}
            restored = tuple(names[index] if want == "*" else want for index, want in enumerate(shape))
            return brain / "projects" / Path(*restored), "client" if shape == ("clients", "*") else kinds[len(shape)]
    if (shape := shape_of(parts, EARLIER_SHAPES)) is not None:
        return brain / "projects" / Path(*placed(parts, EARLIER_SHAPES[shape][1])), kinds[len(shape)]
    root = action_tool().archived_root(folder, brain)
    if root is not None and root != folder:
        raise SystemExit(f"{folder.relative_to(brain).as_posix()} sits in {root.relative_to(brain).as_posix()}, which is archived: "
                         f"unarchive {root.relative_to(brain).as_posix()} first")
    raise SystemExit(f"{folder.relative_to(brain).as_posix()} is not archived: nothing to unarchive")


def action_tool():
    return load_tools()[0]


def code_mask(text: str) -> str:
    """``text`` with its code fences and spans blanked, at the same length: a link there is not a link."""
    text = CODE_FENCE.sub(lambda match: " " * len(match.group(0)), text)
    return CODE_SPAN.sub(lambda match: " " * len(match.group(0)), text)


def entry_rewrite(path: str, base: Path, old: Path, new: Path) -> str | None:
    """``path`` (written in ``base``) with the step that enters ``old`` changed so that it enters ``new``, in the same
    style: an `archive` segment inserted (`missions/m/…` → `missions/archive/m/…`) or removed, or the parent folder's name
    swapped (an earlier place). None when it does not apply."""
    if old.name != new.name:
        return None
    segments, here = path.split("/"), str(base)
    for index, segment in enumerate(segments):
        before, here = here, os.path.normpath(os.path.join(here, segment))
        if here != str(old):
            continue
        if before != str(old.parent):
            return None
        if new.parent == old.parent / "archive":
            return "/".join([*segments[:index], "archive", *segments[index:]])
        if old.parent == new.parent / "archive" and index and segments[index - 1] == "archive":
            return "/".join([*segments[:index - 1], *segments[index:]])
        if old.parent.parent == new.parent.parent and index and segments[index - 1] == old.parent.name:
            return "/".join([*segments[:index - 1], new.parent.name, *segments[index:]])
        return None
    return None


def depth_shift(path: str, levels: int) -> str | None:
    """``path`` written from a folder ``levels`` deeper (`../` added) or shallower (a leading `../` dropped); None when it cannot be."""
    if levels > 0:
        return "../" * levels + path
    if levels < 0 and path.startswith("../" * -levels):
        return path[3 * -levels:]
    return None


def retarget(raw: str, base_old: Path, base_new: Path, old: Path, new: Path) -> str | None:
    """The new text of a link target ``raw`` written in a file that moves from ``base_old`` to ``base_new`` (the same
    folder for a file outside the moved folder) while that folder moves from ``old`` to ``new``; None when the link
    still points where it pointed. A target written as the shortest relative path stays the shortest; another one keeps
    its form, with an `archive` segment inserted or removed where it enters the folder, or one `../` more or less at its
    start when it is written inside the folder; else it becomes the shortest. So `unarchive` gives the text back."""
    if NOT_RELATIVE.match(raw):
        return None
    path, mark, anchor = raw.partition("#")
    if not path:
        return None
    before = os.path.normpath(os.path.join(base_old, path))
    inside = before == str(old) or before.startswith(str(old) + os.sep)
    after = str(new) + before[len(str(old)):] if inside else before
    slash = "/" if path.endswith("/") and len(path) > 1 else ""
    written = path.rstrip("/") if slash else path
    shortest = os.path.relpath(after, base_new).replace(os.sep, "/")
    if written == os.path.relpath(before, base_old).replace(os.sep, "/"):  # the shortest path stays the shortest
        rewritten = shortest
    elif os.path.normpath(os.path.join(base_new, path)) == after:  # another form that still points right is kept
        return None
    else:
        candidate = (entry_rewrite(written, base_old, old, new) if base_old == base_new
                     else depth_shift(written, len(new.parts) - len(old.parts)))
        valid = candidate is not None and os.path.normpath(os.path.join(base_new, candidate)) == after
        rewritten = candidate if valid else shortest
    return None if rewritten == written else rewritten + slash + mark + anchor


def relink_text(text: str, base_old: Path, base_new: Path, old: Path, new: Path) -> tuple[str, list[dict]]:
    """``text`` with its links retargeted (see `retarget`), and the changes: line, target before and after."""
    pieces, changes, last = [], [], 0
    for match in MD_LINK.finditer(code_mask(text)):
        raw = text[match.start(1):match.end(1)]
        target = retarget(raw, base_old, base_new, old, new)
        if target is None:
            continue
        pieces += [text[last:match.start(1)], target]
        last = match.end(1)
        changes.append({"line": text.count("\n", 0, match.start(1)) + 1, "from": raw, "to": target})
    return "".join(pieces) + text[last:], changes


def markdown_files(brain: Path) -> list[Path]:
    """Every Markdown file of the brain, hidden folders and symbolic links left out."""
    found = []
    for folder, folders, files in os.walk(brain):
        base = Path(folder)
        folders[:] = sorted(name for name in folders if not name.startswith(".") and not (base / name).is_symlink())
        found += [base / name for name in sorted(files)
                  if name.lower().endswith(".md") and not name.startswith(".") and not (base / name).is_symlink()]
    return found


def write_atomic(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` in one step, keeping its mode."""
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".archive-", delete=False) as stream:
        stream.write(data)
        temporary = Path(stream.name)
    try:
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def link_check(brain: Path) -> dict:
    """tools/brain/check-links.py on ``brain`` (targets missing from artifacts/ and repos/ reported, not failing)."""
    script = Path(__file__).resolve().with_name("check-links.py")
    result = subprocess.run([sys.executable, str(script), "--allow-missing-local"], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", check=False, env={**os.environ, "BRAIN_DIR": str(brain), "WORK_DIR": str(WORK),
                                                                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    counts = {found.group(1): int(found.group(2)) for line in result.stdout.splitlines() if (found := LINK_COUNTS.match(line))}
    problems = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith(("⛔", "⚠"))]
    return {"exit": result.returncode, "counts": counts, "problems": problems, "error": result.stderr.strip()}


def archive_subject(brains: list[Path], wanted: str, back: bool, action) -> tuple[str, Path, Path, str]:
    """(brain name, resolved brain, folder, label) of what `archive` or `unarchive` (``back``) moves.

    ``wanted`` is a folder below `projects/` given by its path (from the Work root, from a brain, or absolute; a folder
    without a register too), else `clients/<client>` for a whole client, else a project named as for `brief`."""
    path = Path(wanted.strip()).expanduser()
    for candidate in [path] if path.is_absolute() else [WORK / path, *(brain / path for brain in brains)]:
        if candidate.is_dir() and not candidate.is_symlink():
            folder = candidate.resolve()
            for brain in brains:
                root = brain.resolve()
                if folder.is_relative_to(root / "projects") and folder != root / "projects":
                    registers = [register for register in action.registers(root) if register.parent.parent == folder]
                    live = action.live_parts(folder.relative_to(root / "projects").parts)
                    label = (action.project_label(registers[0], root) if registers
                             else f"client {live[1]}" if len(live) == 2 and live[0] == "clients" else folder.name)
                    return brain.name, root, folder, label
    if client := re.fullmatch(r"clients/([^/]+)", wanted.strip().strip("/")):
        found = [(brain.name, brain.resolve(), brain.resolve() / "projects/clients" / ("archive" if back else "") / client.group(1))
                 for brain in brains]
        found = [item for item in found if item[2].is_dir() and not item[2].is_symlink() and client.group(1) != "archive"]
        if len(found) > 1:
            raise SystemExit(f"several brains have the client {client.group(1)}: give --brain NAME")
        if found:
            return (*found[0], f"client {client.group(1)}")
        raise SystemExit(f"no {'archived ' if back else ''}client {client.group(1)}" + ("" if back else " (an archived client is unarchived)")
                         + ": " + ", ".join(brain.name for brain in brains))
    name, root, register = resolve_project(brains, wanted, action, "archived" if back else "all", "",
                                           live_hint="it is not archived: nothing to unarchive")
    return name, root, register.parent.parent, action.project_label(register, root)


def cmd_archive(brains: list[Path], only: str | None, wanted: str, back: bool, write: bool, as_json: bool) -> int:
    """`archive` (``back`` False) or `unarchive` one project or client: a dry run unless ``write``."""
    verb = "unarchive" if back else "archive"
    action = load_tools()[0]
    name, brain, old, label = archive_subject(pick_brains(brains, only), wanted, back, action)
    if not back and action.live_parts(old.relative_to(brain / "projects").parts) == ("internal", "setup"):
        raise SystemExit("setup is the brain's own project (actions without a mission, prefix SET): it is never archived")
    new, kind = archive_destination(brain, old, back)
    if new.exists() or new.is_symlink():
        raise SystemExit(f"cannot {verb} {label}: {shown(name, brain, new)} already exists")

    if not back:  # finished only: every action of the project, or of every mission of the client, closed or cancelled
        still = [{"id": item["id"], "state": item["state"], "title": item["title"], "project": item["project"],
                  "register": shown(name, brain, path)}
                 for path in action.registers(brain) if path.is_relative_to(old)
                 for item in action.load(path, brain) if item["state"] in action.OPEN_STATES]
        if still:
            option = "" if brain == (default_brain() or Path()).resolve() else f"--brain {shlex.quote(name)} "
            if as_json:
                print(json.dumps({"command": verb, "brain": name, "project": label, "kind": kind, "refused": "open actions",
                                  "open_actions": still}, ensure_ascii=False, indent=2))
            else:
                print(f"cannot archive {label} ({name}): {len(still)} action(s) still to do, in progress or waiting:", file=sys.stderr)
                for item in still:
                    print(f"  {item['id']} [{item['state']}] {clip(item['title'])}" + (f"  ({item['project']})" if kind == "client" else ""),
                          file=sys.stderr)
                print(f"Close or cancel them first (uv run tools/brain/action.py {option}update ID --state done|cancelled), "
                      "then archive again.", file=sys.stderr)
            return 1

    changed: dict[Path, tuple[bytes, str, Path]] = {}  # file now -> (its bytes, its new text, where it is after the move)
    links: list[dict] = []
    for path in markdown_files(brain):
        moved = path.is_relative_to(old)
        after = new / path.relative_to(old) if moved else path
        data = path.read_bytes()
        text = data.decode("utf-8", errors="surrogateescape")
        relinked, changes = relink_text(text, path.parent, after.parent, old, new)
        if changes:
            changed[path] = (data, relinked, after)
            links += [{"file": shown(name, brain, after), **change} for change in changes]
    mention = re.compile(re.escape(old.relative_to(brain).as_posix()) + r"(?![\w-])")
    mentions = []
    data_files = sorted((brain / ".data").glob("*.json")) if (brain / ".data").is_dir() else []
    for path in [*markdown_files(brain), *data_files]:
        text = changed[path][1] if path in changed else path.read_text(encoding="utf-8", errors="replace")
        if count := len(mention.findall(text)):
            where = new / path.relative_to(old) if path.is_relative_to(old) else path
            mentions.append({"file": shown(name, brain, where), "count": count})

    created, removed, check = [], [], None
    if write:
        parent = new.parent
        while not parent.exists():
            created.insert(0, parent)
            parent = parent.parent
        written: list[tuple[Path, bytes]] = []
        try:
            for folder in created:
                folder.mkdir()
            old.rename(new)
            for path, (data, text, after) in changed.items():
                if after.read_bytes() != data:
                    raise OSError(f"{shown(name, brain, after)} changed while it was being moved")
                write_atomic(after, text.encode("utf-8", errors="surrogateescape"))
                written.append((after, data))
        except OSError as error:  # put everything back as it was
            for path, data in reversed(written):
                write_atomic(path, data)
            if new.exists() and not old.exists():
                new.rename(old)
            for folder in reversed(created):
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
            raise SystemExit(f"cannot {verb} {label}: {error}; nothing was changed") from None
        source_parent = old.parent
        if source_parent.name == "archive" and not any(source_parent.iterdir()):
            source_parent.rmdir()  # an archive/ folder left empty (archive created it): unarchive gives the tree back as it was
            removed.append(source_parent)
        check = link_check(brain)

    data = {"command": verb, "brain": name, "project": label, "kind": kind, "from": shown(name, brain, old), "to": shown(name, brain, new),
            "write": write, "moved": write, "created_dirs": [shown(name, brain, folder) for folder in created],
            "removed_dirs": [shown(name, brain, folder) for folder in removed], "files_changed": len(changed), "links": links,
            "mentions_left": mentions, "link_check": check}
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if check is None or check["exit"] == 0 else 1
    done = {"archive": "archived", "unarchive": "unarchived"}[verb]
    print(f"{done} {label} ({name})" if write else f"{verb} {label} ({name}) — dry run: nothing is moved, --write applies it")
    print(f"  {'moved' if write else 'move'}  {data['from']}  →  {data['to']}")
    for folder in data["created_dirs"]:
        print(f"  created  {folder}")
    for folder in data["removed_dirs"]:
        print(f"  removed  {folder} (empty)")
    print(f"  links: {len(links)} {'rewritten' if write else 'to rewrite'} in {len(changed)} file(s)" if links else "  links: none to rewrite")
    for item in links:
        print(f"    {item['file']}:{item['line']}  {item['from']}  →  {item['to']}")
    if mentions:
        print("  not links, left as they are: " + ", ".join(f"{item['file']} ({item['count']} mention{'s' if item['count'] > 1 else ''})"
                                                         for item in mentions))
    if check is not None:
        counts = check["counts"]
        print(f"  link check of {name}: exit {check['exit']} — dead {counts.get('dead (md)', '?')} (md), {counts.get('dead (wiki)', '?')} (wiki), "
              f"cross-brain {counts.get('cross-brain', '?')}, unverified local {counts.get('unverified local links', 0)}"
              + (f" — {check['error']}" if check["error"] else ""))
        for line in check["problems"][:10]:
            print(f"    {line}")
    return 0 if check is None or check["exit"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("brains", help="list the brains found, their tracked transcripts, scope and description")
    mp = sub.add_parser("map", help="where everything is: brains, clients, projects, pages, registers and their state (read-only)")
    mp.add_argument("--json", action="store_true", help="structured output with stable keys instead of text")
    mp.add_argument("--brain", metavar="NAME", help="only this brain (as listed by `brains`)")
    shown_projects = mp.add_mutually_exclusive_group()
    shown_projects.add_argument("--archived", action="store_true", help="only the archived projects, flagged [archived]")
    shown_projects.add_argument("--all", action="store_true", help="the live and the archived projects, these flagged [archived]")
    brain_help = "only this brain (as listed by `brains`)"
    br = sub.add_parser("brief", help="compact briefing of one project: state, open actions, decisions, timeline, what to read next (read-only)")
    br.add_argument("project", help="register, project folder, client/mission or label, as for `action.py list --project`")
    br.add_argument("--brain", metavar="NAME", help=brain_help)
    br.add_argument("--words", type=int, default=150, metavar="N", help="word cap of the state section (default 150)")
    br.add_argument("--limit", type=int, default=10, metavar="N", help="open actions shown, late ones first (default 10)")
    br.add_argument("--decisions", type=int, default=5, metavar="N", help="decisions shown (default 5)")
    br.add_argument("--archived", action="store_true", help="let PROJECT name an archived project (refused otherwise)")
    br.add_argument("--json", action="store_true", help="the same fields as JSON")
    du = sub.add_parser("due", help="late actions and actions due within N days, by project (read-only)")
    du.add_argument("--days", type=int, default=7, metavar="N", help="how far ahead to look (default 7)")
    du.add_argument("--brain", metavar="NAME", help=brain_help)
    du.add_argument("--json", action="store_true", help="structured output instead of text")
    ch = sub.add_parser("changes", help="timeline entries, actions created or closed and decisions dated since a day, by project (read-only)")
    ch.add_argument("--since", required=True, metavar="DATE|Nd", help="first day, YYYY-MM-DD, or a number of days back (7d)")
    ch.add_argument("--project", metavar="P", help="only this project, named as for `brief`")
    ch.add_argument("--limit", type=int, metavar="N",
                    help=f"events shown per project, newest first, cut by whole days (default {CHANGES}; with --project, every event)")
    ch.add_argument("--brain", metavar="NAME", help=brain_help)
    ch.add_argument("--json", action="store_true", help="structured output instead of text")
    fi = sub.add_parser("find", help="search every Markdown page of the brains, ranked by kind (read-only)")
    fi.add_argument("term", nargs="+", help="text to look for, as written: case and accents do not count (several words: that phrase)")
    fi.add_argument("--in", dest="kinds", metavar="KIND[,KIND]", help="only these kinds: " + ", ".join(KINDS))
    fi.add_argument("--project", metavar="P", help="only this project's folder, named as for `brief`")
    fi.add_argument("--per-file", type=int, default=PER_FILE, metavar="N",
                    help=f"hits shown per file (default {PER_FILE}, 0 for all); in a register, one hit per action or decision")
    fi.add_argument("--limit", type=int, default=40, metavar="N", help="hits shown in all (default 40)")
    searched = fi.add_mutually_exclusive_group()
    searched.add_argument("--archived", action="store_true", help="search the archived projects only (never searched otherwise)")
    searched.add_argument("--all", action="store_true",
                          help="search everything: the live pages, the archives (action archives, people/archive/…) and the archived projects")
    fi.add_argument("--brain", metavar="NAME", help=brain_help)
    fi.add_argument("--json", action="store_true", help="structured output instead of text, with the counts by kind")
    se = sub.add_parser("section", help="the outline of a Markdown page of a brain, or one of its sections (read-only)")
    se.add_argument("file", metavar="FILE[:LINE]", help="path as `find` and `brief` print it; with :LINE, the section that holds that line")
    se.add_argument("heading", nargs="*", metavar="HEADING",
                    help="title of the section to print (exact, else its start, else a part); `summary` for the abstract")
    se.add_argument("--words", type=int, metavar="N",
                    help=f"word cap: of the window around FILE:LINE (default {WINDOW}), of a section named by its heading (default {SECTION})")
    se.add_argument("--brain", metavar="NAME", help=brain_help + "; FILE may then be given from that brain")
    se.add_argument("--json", action="store_true", help="structured output instead of text")
    pe = sub.add_parser("person", help="who someone is, from their people page, and the open actions they carry (read-only)")
    pe.add_argument("name", nargs="+", help="slug of the page, or words of the name or of one alias")
    pe.add_argument("--words", type=int, default=120, metavar="N", help="word cap of the identity part (default 120)")
    pe.add_argument("--limit", type=int, default=10, metavar="N", help="open actions shown (default 10)")
    pe.add_argument("--brain", metavar="NAME", help=brain_help)
    pe.add_argument("--json", action="store_true", help="structured output instead of text")
    for verb, text in (("archive", "move a finished project whole into its archive/ folder and rewrite the links that follow it (dry run unless --write)"),
                       ("unarchive", "move an archived project back where it was, the exact inverse of archive (dry run unless --write)")):
        ar = sub.add_parser(verb, help=text)
        ar.add_argument("project", help="named as for `brief`, clients/<client> for a whole client, or a folder path"
                        + ("" if verb == "archive" else "; an archived one"))
        ar.add_argument("--write", action="store_true", help="move the folder and rewrite the links (default: print what would change)")
        ar.add_argument("--brain", metavar="NAME", help=brain_help)
        ar.add_argument("--json", action="store_true", help="structured output instead of text")
    tr = sub.add_parser("transcripts", help="merged transcript states (status, brain, file)")
    group = tr.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true", help="transcripts listed by no brain")
    group.add_argument("--where", metavar="FILE", help="which brain owns FILE, and its status")
    args, extra = parser.parse_known_args()
    words = {"find": "term", "section": "heading", "person": "name"}.get(args.command)
    if extra and words and not any(word.startswith("-") for word in extra):
        getattr(args, words).extend(extra)  # before Python 3.12, words typed after an option are not attached to the others
    elif extra:
        parser.error("unrecognized arguments: " + " ".join(extra))

    brains = discover()
    check_expected(brains)
    if args.command == "brains":
        return cmd_brains(brains)
    if args.command == "map":
        return cmd_map(brains, args.brain, args.json, "all" if args.all else "archived" if args.archived else "live")
    if args.command == "brief":
        return cmd_brief(brains, args)
    if args.command == "due":
        return cmd_due(brains, args.brain, args.days, args.json)
    if args.command == "changes":
        return cmd_changes(brains, args.brain, args.since, args.project, args.limit, args.json)
    if args.command == "find":
        return cmd_find(brains, args.brain, " ".join(args.term), args.limit, args.per_file, args.kinds,
                        "all" if args.all else "archived" if args.archived else "live", args.json, args.project)
    if args.command == "section":
        return cmd_section(brains, args.brain, args.file, args.heading, args.words, args.json)
    if args.command == "person":
        return cmd_person(brains, args.brain, " ".join(args.name), args.words, args.limit, args.json)
    if args.command in {"archive", "unarchive"}:
        return cmd_archive(brains, args.brain, args.project, args.command == "unarchive", args.write, args.json)
    return cmd_transcripts(brains, args.new, args.where)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 even through a pipe on Windows, where the default is the ANSI code page
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    sys.exit(main())
