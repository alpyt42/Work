#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Create, read and edit the actions of a brain's registers (`projects/**/state/actions.md`).

One tool for the agents (command line) and for the local web interface (tasks-web runs it for
every write), so that an action is always written the same way:

    - [ ] **DEM-101** — Owner — Title ⏫ ➕ 2026-10-13 📅 2026-10-20
        - source: [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)
        - created: 2026-10-13 14:32
        - updated: 2026-10-14 09:05
        - 14/10: history entry

`➕` carries the creation date for the Obsidian Tasks plugin, which reads dates only; the
`created:` sub-bullet keeps the creation date and time (Europe/Paris, to the minute). Both are
written once, at creation. `updated:` moves only when a change made through this tool really
changes the action (fields, status, history): a write that leaves the action as it was (the same
status set again, a note added then deleted...) keeps the previous value, and an action brought
back to the state of the register's last Git synchronization point gets back the `updated:` of that version
(also repairing a stale stamp left by an earlier edit);
any other change stamps the current time. The due date stays `📅` on the line.

A group of tasks is a label, not a parent task: at most one `#group/<slug>` tag at the end
of the title, just before the Tasks emojis (`… Title #group/ingestion-workshop ➕ 2026-10-13`).
`--group SLUG` writes it (`--group ""` on `update` removes it, no option keeps it); a `--title`
that itself ends with a valid `#group/…` tag is refused (use `--group`).

A subtask is one step of an action's short checklist: a checkbox sub-bullet `    - [ ] text`
or `    - [x] text ✅ YYYY-MM-DD` (the date Obsidian Tasks appends when the box is ticked there),
written directly under the action line, before every other sub-bullet. It has no ID, owner or
date of its own: it inherits the action's. At most 15 words, at most 10 per action. A subtask
change refreshes `updated:` and adds no history entry; closing an action leaves its open subtasks
unticked and says so in `warnings`. The history (`notes` of `show`, the indices of `history edit`
and `remove`) leaves the subtasks out, which have their own indices (`subtasks` of `show`).

A history entry holds at most 35 words (`history add` and `edit`; the `moved from …` entry that
`move` writes itself is exempt): one change of state, owner, due date or blocker, the source
linked once. A text that starts with the entry's own `DD/MM:` loses it; another date is refused.

A brain written with the earlier French labels is converted once with
`uv run tools/brain/migrate-english.py`.

Commands (from the Work root, `uv run tools/brain/action.py <command> --help` for details):

    list      [--project P] [--state open|closed|all] [--owner O] [--due-before D] [--limit N] [--table]
              [--archived]
    board     [--write [PATH]] [--watch]     complete view by project (terminal, VS Code preview)
    show      ID [--text [--last N]]         an archived action too, flagged `archived`; --text: compact
                                             plain text with the last N history entries (default 3, 0: all)
    create    --project P --title T --owner O --source S [--state] [--priority] [--due]
              [--scheduled] [--due-note N] [--group SLUG] [--prefix XXX]
              (--prefix: only for an empty register whose header and archives give none)
    update    ID [--title] [--owner] [--state] [--priority] [--due] [--scheduled] [--group SLUG]
              [--closed-on D]
    history   add ID --text T [--date D]  |  edit ID --index N --text T [--date D]  |  remove ID --index N
    subtask   add ID --text T [--position N]  |  toggle ID --index N [--done|--undone]  |  edit ID --index N --text T
              |  remove ID --index N  |  move ID --index N --to M          (indices from 0, as `show` gives them)
    move      ID --to P                      to another register of the same client, ID unchanged
    check     [--register R] [--archived]    format errors (exit 1) and warnings of the registers
    delete    ID
    sweep     [--write|--check] [--archive] [--register R]   put each action under its state's section
    archive   [--write|--check] [--days N] [--today D]       move old closures to actions-archive-YYYY.md

An archived project (moved whole by `brain-state.py archive` into the `archive/` folder at its own
level: `projects/clients/<client>/missions/archive/<mission>/`, `projects/internal/archive/<project>/`,
or with its whole client `projects/clients/archive/<client>/`; the earlier places `projects/archive/<project>/`
and `projects/clients/<client>/archive/<mission>/` still count) keeps its label (`acme / demo`) and is out of the context:
`list`, `board`, `sweep`, `archive` and `check` leave it out (`--archived` brings it back into `list`,
where its actions carry `"project_archived": true`, and into the format part of `check`; its IDs always
count for duplicates and for the next ID); `create`, `update`, `history`, `subtask`, `move` and `delete`
refuse its actions (exit code 2: unarchive it first); `show` still reads them, flagged
`"project_archived": true` (`(archived project)` with `--text`).

Every write accepts `--dry-run` (print the result, write nothing) and the optimistic-lock options
`--expect-version` (hash of the action line) and `--expect-details-version` (hash of the block)
used by the web interface. A status change moves the action to the section of its state (the
`sweep`, for this action only); a closure gets `✅`/`❌` with today's date, or
`--closed-on` for the date of the evidence; a reopening drops it.

Output is JSON on stdout, except the text of `list --table` and `show --text`: `show ID --text`
prints the action line as written, one line of dates (project, due date and note, created, updated,
closed), the subtasks under `subtasks, 1 of 3 done:`, the source, the latest history entries under
`history, last 3 of 12:` and the `file:line` of the action from the Work root, flagged `(archived)`
when it comes from an archive. `list --table` and `board` show the subtask progress (` 1/3`) after the title.
Exit codes: 0 done, 2 invalid request, 3 not found, 4 conflict.
`--brain PATH` or BRAIN_DIR selects another brain; ACTION_NOW (`YYYY-MM-DD HH:MM`) fixes the
clock for tests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WORK = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parents[2])).resolve()


def default_brain_dir() -> Path:
    """The default brain of WORK (rule of tools/machine/work_config.py); `WORK/brain` when there is none."""
    spec = importlib.util.spec_from_file_location("work_config", Path(__file__).resolve().parents[1] / "machine/work_config.py")
    assert spec and spec.loader
    work_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(work_config)
    try:
        return work_config.default_brain(WORK) or WORK / "brain"
    except work_config.ConfigError as error:
        raise SystemExit(f"work config error: {error}") from None
    except OSError:
        return WORK / "brain"


BRAIN = Path(os.environ["BRAIN_DIR"] if "BRAIN_DIR" in os.environ else default_brain_dir()).resolve()

# --- Registers: sections and archive (formerly manage-action.py) -------------------------------------

ACTION = re.compile(r"^- \[(.)\] \*\*([A-Z]{2,5}-\d{3})\*\*")
CLOSED_ON = re.compile(r"[✅❌]\s*(\d{4}-\d{2}-\d{2})\b")
H1_PROJECT = re.compile(r"^#\s+Actions\s*[—–-]\s*(.+?)\s*$")
DEFAULT_DAYS = 30

TITLES = {"open": "Open", "done": "Done", "cancelled": "Cancelled"}
SECTION_KEYS = {title.lower(): key for key, title in TITLES.items()}


def section_key(title: str) -> str | None:
    """`open`, `done` or `cancelled` for a section title, else None."""
    return SECTION_KEYS.get(title.strip().lower())


def history_prefix(day: str) -> str:
    """The `DD/MM: ` prefix of a history entry for an ISO day."""
    return f"{day[8:10]}/{day[5:7]}: "


class ArchiveError(Exception):
    """A register cannot be archived; nothing was written for it."""


@dataclass
class Block:
    """An action line with its indented sub-bullets (and the blank lines between them)."""

    start: int
    end: int  # exclusive
    action_id: str
    state: str
    closed: date | None
    invalid_date: str | None
    section: str  # lower-cased `## ` heading the block sits under


@dataclass
class Plan:
    register: Path
    moves: dict[int, list[Block]] = field(default_factory=dict)  # year -> blocks
    outputs: dict[Path, str] = field(default_factory=dict)  # file -> new text
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(len(blocks) for blocks in self.moves.values())


def paris_today() -> date:
    return datetime.now(ZoneInfo("Europe/Paris")).date()


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{value}' (expected YYYY-MM-DD)") from None


def split_text(text: str) -> tuple[list[str], str]:
    """Lines (the last item is '' when the text ends with a newline) and the line ending."""
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.split(eol), eol


def parse_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    section = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            section = line[3:].strip().lower()
        match = ACTION.match(line)
        if not match:
            index += 1
            continue
        state, action_id = match.groups()
        end = index + 1
        while end < len(lines):
            probe = end
            while probe < len(lines) and not lines[probe].strip():
                probe += 1
            if probe < len(lines) and lines[probe].startswith("    ") and lines[probe].strip():
                end = probe + 1
            else:
                break
        closed = None
        invalid = None
        found = CLOSED_ON.findall(line)
        if found:
            try:
                closed = date.fromisoformat(found[-1])
            except ValueError:
                invalid = found[-1]
        blocks.append(Block(index, end, action_id, state, closed, invalid, section))
        index = end
    return blocks


def project_name(register_lines: list[str], register: Path) -> str:
    for line in register_lines:
        if line.startswith("# "):
            found = H1_PROJECT.match(line)
            if found:
                return found.group(1)
            break
    return register.parent.parent.name


def new_archive(project: str, year: int) -> list[str]:
    title = f"# Actions archive {year} — {project}"
    quote = f"> Closed actions of {project} archived for {year}; the live register is [actions.md](actions.md). IDs stay reserved."
    return [title, "", quote, "", f"## {TITLES['done']}", "", f"## {TITLES['cancelled']}", ""]


def section_bounds(lines: list[str], key: str) -> tuple[int, int] | None:
    """Heading index and end (exclusive) of the `open`, `done` or `cancelled` section, or None."""
    for index, line in enumerate(lines):
        if line.startswith("## ") and section_key(line[3:]) == key:
            end = index + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            return index, end
    return None


def insert_block(lines: list[str], key: str, block: list[str], closed: date) -> None:
    """Insert in the `key` section, before the first dated item that closed strictly earlier."""
    bounds = section_bounds(lines, key)
    if bounds is None:
        while lines and lines[-1] == "":
            lines.pop()
        lines.extend(["", f"## {TITLES[key]}", ""])
        bounds = section_bounds(lines, key)
    assert bounds is not None
    heading, end = bounds
    items = parse_blocks(lines[heading:end])
    position = None
    for item in items:
        if item.closed is not None and item.closed < closed:
            position = heading + item.start
            break
    if position is None:
        position = heading + items[-1].end if items else heading + 1
    lines[position:position] = block
    after = position + len(block)
    if after < len(lines) and lines[after].startswith("## "):
        lines.insert(after, "")


def tidy_junctions(lines: list[str], junctions: list[int]) -> list[str]:
    """Repair the blank lines where blocks were removed (positions index the kept lines)."""
    for position in sorted(set(junctions), reverse=True):
        if position >= len(lines):
            while len(lines) > 1 and lines[-1] == "" and lines[-2] == "":
                lines.pop()
            continue
        before = lines[position - 1] if position else ""
        if position and before == "" and lines[position] == "":
            del lines[position]
        elif before.startswith("## ") and lines[position] == "":
            probe = position
            while probe < len(lines) and lines[probe] == "":
                probe += 1
            if probe < len(lines) and not lines[probe].startswith("#"):
                del lines[position:probe]
    return lines


def plan_register(register: Path, today: date, days: int) -> Plan:
    plan = Plan(register)
    raw = register.read_bytes().decode("utf-8")
    lines, eol = split_text(raw)
    cutoff = today - timedelta(days=days)
    blocks = parse_blocks(lines)

    selected: list[Block] = []
    for block in blocks:
        if block.state not in STATE_SECTION or STATE_SECTION[block.state] == "open":
            continue
        if block.invalid_date:
            plan.warnings.append(f"{block.action_id}: invalid closing date {block.invalid_date}, left in the register")
            continue
        if block.closed is None or block.closed >= cutoff:
            continue
        if section_key(block.section) not in {"done", "cancelled"}:
            plan.warnings.append(f"{block.action_id} closed on {block.closed.isoformat()} but filed under '{block.section or 'no section'}': file it under {TITLES['done']} or {TITLES['cancelled']} first, not moved")
            continue
        selected.append(block)
    if not selected:
        return plan

    seen: set[str] = set()
    for block in selected:
        if block.action_id in seen:
            raise ArchiveError(f"ID {block.action_id} appears several times in the register")
        seen.add(block.action_id)
    for archive in sorted(register.parent.glob("actions-archive-*.md")):
        if archive.is_symlink():
            raise ArchiveError(f"{archive.name} is a symbolic link")
        known = {m.group(2) for m in map(ACTION.match, archive.read_text(encoding="utf-8").splitlines()) if m}
        clash = sorted(seen & known)
        if clash:
            raise ArchiveError(f"ID already in {archive.name}: {', '.join(clash)} (nothing is written for this register)")

    project = project_name(lines, register)
    by_year: dict[int, list[Block]] = {}
    for block in selected:
        assert block.closed is not None
        by_year.setdefault(block.closed.year, []).append(block)
    for year, year_blocks in sorted(by_year.items()):
        target = register.parent / f"actions-archive-{year}.md"
        if target.is_symlink():
            raise ArchiveError(f"{target.name} is a symbolic link")
        if target.exists():
            archive_lines, archive_eol = split_text(target.read_bytes().decode("utf-8"))
        else:
            archive_lines, archive_eol = new_archive(project, year), eol
        # Stable sort newest first: equal dates keep register order, after existing ones.
        for block in sorted(year_blocks, key=lambda item: item.closed, reverse=True):  # type: ignore[arg-type, return-value]
            assert block.closed is not None
            insert_block(archive_lines, STATE_SECTION[block.state], lines[block.start:block.end], block.closed)
        plan.outputs[target] = archive_eol.join(archive_lines)
        plan.moves[year] = year_blocks

    removed = {i for block in selected for i in range(block.start, block.end)}
    kept: list[str] = []
    junctions: list[int] = []
    for index, line in enumerate(lines):
        if index in removed:
            if index - 1 not in removed:
                junctions.append(len(kept))
            continue
        kept.append(line)
    tidy = tidy_junctions(kept, junctions)
    if raw and not raw.endswith(eol):
        while tidy and tidy[-1] == "":
            tidy.pop()
    plan.outputs[register] = eol.join(tidy)
    return plan


def atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(temp, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def apply_plan(plan: Plan) -> None:
    """Archives first, register last; restore the archives if any write fails."""
    snapshots: dict[Path, bytes | None] = {}
    order = [path for path in plan.outputs if path != plan.register] + [plan.register]
    try:
        for path in order:
            snapshots[path] = path.read_bytes() if path.exists() else None
            atomic_write_text(path, plan.outputs[path])
    except Exception:
        for path, previous in snapshots.items():
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_text(path, previous.decode("utf-8"))
            except OSError:
                pass
        raise


def registers_of(brain: Path) -> list[Path]:
    found = []
    for register in sorted((brain / "projects").glob("**/state/actions.md")):
        if register.is_symlink() or register.resolve() != register or not register.is_file():
            continue
        if brain not in register.parents:
            continue
        found.append(register)
    return found


def display(path: Path) -> str:
    try:
        return path.relative_to(WORK).as_posix()
    except ValueError:
        return path.as_posix()


OPEN_STATES = {" ", "/", "w"}
DONE_STATES = {"x", "X"}
CANCELLED_STATES = {"-"}
STATE_SECTION = {**{s: "done" for s in DONE_STATES}, **{s: "cancelled" for s in CANCELLED_STATES}, **{s: "open" for s in OPEN_STATES}}


@dataclass
class SweepPlan:
    register: Path
    moves: list[tuple[str, str, str]] = field(default_factory=list)  # (id, from, to)
    warnings: list[str] = field(default_factory=list)
    output: str | None = None


def insert_open(lines: list[str], block: list[str]) -> None:
    """Append at the end of the `open` section."""
    bounds = section_bounds(lines, "open")
    assert bounds is not None
    heading, end = bounds
    items = parse_blocks(lines[heading:end])
    position = heading + items[-1].end if items else heading + 1
    lines[position:position] = block
    after = position + len(block)
    if after < len(lines) and lines[after].startswith("## "):
        lines.insert(after, "")


def plan_sweep(register: Path, today: date) -> SweepPlan:
    return sweep_text(register.read_bytes().decode("utf-8"), today, register)


def sweep_text(raw: str, today: date, register: Path, only: set[str] | None = None) -> SweepPlan:
    """Plan the sweep of a register text; `only` restricts it to those action IDs."""
    plan = SweepPlan(register)
    lines, eol = split_text(raw)
    blocks = parse_blocks(lines)

    seen: set[str] = set()
    for block in blocks:
        if block.action_id in seen:
            raise ArchiveError(f"ID {block.action_id} appears several times in the register")
        seen.add(block.action_id)

    selected = []
    for block in blocks:
        if only is not None and block.action_id not in only:
            continue
        target = STATE_SECTION.get(block.state)
        if target is None:
            plan.warnings.append(f"{block.action_id}: unknown state [{block.state}], left in place")
            continue
        if section_key(block.section) is None:
            plan.warnings.append(f"{block.action_id}: filed under '{block.section or 'no section'}', unknown section, left in place")
            continue
        if section_key(block.section) == target:
            continue
        if section_bounds(lines, target) is None:
            plan.warnings.append(f"{block.action_id}: section '{TITLES[target]}' missing from the register, left in place")
            continue
        if target != "open" and block.closed is None and not block.invalid_date:
            plan.warnings.append(f"{block.action_id}: closed without a ✅/❌ date, to date with the evidence")
        if block.invalid_date:
            plan.warnings.append(f"{block.action_id}: invalid closing date {block.invalid_date}")
        if target == "open" and (block.closed or block.invalid_date):
            plan.warnings.append(f"{block.action_id}: reopened but a ✅/❌ date remains on the line, to remove")
        selected.append((block, target))
    if not selected:
        return plan

    removed = {i for block, _ in selected for i in range(block.start, block.end)}
    kept: list[str] = []
    junctions: list[int] = []
    for index, line in enumerate(lines):
        if index in removed:
            if index - 1 not in removed:
                junctions.append(len(kept))
            continue
        kept.append(line)
    tidy = tidy_junctions(kept, junctions)

    # Open actions keep register order; closed ones go newest first (no date = newest).
    ordered = sorted(
        selected,
        key=lambda item: (item[1] != "open", -(item[0].closed or today).toordinal() if item[1] != "open" else item[0].start),
    )
    for block, target in ordered:
        text = lines[block.start:block.end]
        while text and not text[-1].strip():
            text.pop()
        if target == "open":
            insert_open(tidy, text)
        else:
            insert_block(tidy, target, text, block.closed or today)
        plan.moves.append((block.action_id, block.section, TITLES[target].lower()))

    if raw and not raw.endswith(eol):
        while tidy and tidy[-1] == "":
            tidy.pop()
    plan.output = eol.join(tidy)
    return plan


def run_archive(register: Path, name: str, today: date, args: argparse.Namespace) -> tuple[int, int]:
    """Returns (actions moved or to move, errors)."""
    try:
        plan = plan_register(register, today, args.days)
        if plan.count and args.write:
            apply_plan(plan)
    except (ArchiveError, OSError, UnicodeDecodeError) as error:
        print(f"ERROR {name}: {error}", file=sys.stderr)
        return 0, 1
    if not args.quiet:
        for warning in plan.warnings:
            print(f"WARNING {name}: {warning}")
        if plan.count:
            targets = " ; ".join(f"actions-archive-{year}.md ({', '.join(b.action_id for b in blocks)})" for year, blocks in sorted(plan.moves.items()))
            print(f"{name}: archive {plan.count} action(s){' moved' if args.write else ''} → {targets}")
    return plan.count, 0


def run_sweep(register: Path, name: str, today: date, args: argparse.Namespace) -> tuple[int, int]:
    try:
        plan = plan_sweep(register, today)
        if plan.output is not None and args.write:
            atomic_write_text(register, plan.output)
    except (ArchiveError, OSError, UnicodeDecodeError) as error:
        print(f"ERROR {name}: {error}", file=sys.stderr)
        return 0, 1
    if not args.quiet:
        for warning in plan.warnings:
            print(f"WARNING {name}: {warning}")
        for action_id, origin, target in plan.moves:
            print(f"{name}: sweep {action_id} {origin or 'no section'} → {target}")
    return len(plan.moves), 0


# --- Single actions ------------------------------------------------------------------------------

ACTION_RE = re.compile(r"^- \[([ /wx-])\] \*\*([A-Z]{2,5}-\d{3})\*\* — ([^—]+?) — (.+)$")
ID_RE = re.compile(r"\b([A-Z]{2,5})-(\d{3})\b")
RESERVED_PREFIX = re.compile(r"(?i:pr[eé]fix\w*)[^`\n]{0,40}`([A-Z]{2,5})`")  # "Reserved prefix: `SET`" in a register header
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOSURE_RE = re.compile(r"\s+[✅❌]\s+(\d{4}-\d{2}-\d{2})$")
CREATED_RE = re.compile(r"\s+➕\s+(\d{4}-\d{2}-\d{2})")
DUE_RE = re.compile(r"\s+📅\s+(\d{4}-\d{2}-\d{2})")
SCHEDULED_RE = re.compile(r"\s+⏳\s+(\d{4}-\d{2}-\d{2})")
PRIORITY_RE = re.compile(r"\s+(⏫|🔼|🔽)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
SOURCE_RE = re.compile(r"-\s*source\s*:", re.IGNORECASE)
CREATED_AT_RE = re.compile(r"-\s*created\s*:\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", re.IGNORECASE)
UPDATED_AT_RE = re.compile(r"-\s*updated\s*:\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?", re.IGNORECASE)
HISTORY_DATE_RE = re.compile(r"^    - (\d{2}/\d{2}: )")
MD_LINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")
LOOSE_ACTION_RE = re.compile(r"^\s*[-*] \[.?\]\s*\*\*([A-Z]{2,5}-\d{3})\*\*")
PROTECTED_RE = re.compile(r"-\s*(source|created|updated)\s*:", re.IGNORECASE)
DUE_NOTE_RE = re.compile(r"-\s*due\s*:\s*(.*)", re.IGNORECASE)
STATUS = {" ", "/", "w", "x", "-"}
PRIORITY = {"", "⏫", "🔼", "🔽"}
STATE_LABELS = {" ": "To do", "/": "In progress", "w": "Waiting", "x": "Done", "-": "Cancelled"}
STATE_ALIASES = {
    " ": " ", "todo": " ", "open": " ",
    "/": "/", "doing": "/", "in-progress": "/",
    "w": "w", "waiting": "w",
    "x": "x", "done": "x",
    "-": "-", "cancelled": "-", "canceled": "-",
}
PRIORITY_ALIASES = {
    "": "", "none": "", "normal": "",
    "⏫": "⏫", "high": "⏫",
    "🔼": "🔼", "medium": "🔼",
    "🔽": "🔽", "low": "🔽",
}
RESERVED = ("➕", "📅", "⏳", "⏫", "🔼", "🔽", "✅", "❌")
HISTORY_WORDS = 35  # words of one history entry (a link counts as its label)
SUBTASK_WORDS = 15  # words of one subtask
SUBTASKS_MAX = 10  # subtasks of one action
SUBTASK_RE = re.compile(r"^- \[(.)\](?:\s+(.*))?$")  # first line of a checkbox sub-bullet, without its four spaces
SUBTASK_DONE_RE = re.compile(r"\s*✅\s*(\d{4}-\d{2}-\d{2})\s*$")  # the done date Obsidian Tasks appends
HISTORY_LEAD_RE = re.compile(r"^(\d{2})/(\d{2}) ?:\s*")  # a `DD/MM:` the text itself starts with
STRONG_ID_RE = re.compile(r"\*\*[A-Z]{2,5}-\d{3}\*\*")
TASKS_META_RE = re.compile(r"\s+(?:#group/\S+\s*)?(?:[⏫🔼🔽➕📅⏳]|$)")  # where a line's group tag and Tasks metadata start
GROUP_LIMIT = 40
GROUP_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
GROUP_RE = re.compile(GROUP_SLUG)
GROUP_TAG_RE = re.compile(r"(?<!\S)#group/(\S*)")
TRAILING_GROUP_RE = re.compile(rf"\s+#group/({GROUP_SLUG})$")
EXIT = {"bad_request": 2, "not_found": 3, "conflict": 4}
TZ = ZoneInfo("Europe/Paris")


class ActionError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(message)


# --- Clock and validation ------------------------------------------------------------------------


def now() -> datetime:
    fixed = os.environ.get("ACTION_NOW", "").strip()
    if fixed:
        return datetime.strptime(fixed, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    return datetime.now(TZ).replace(second=0, microsecond=0)


def today() -> str:
    return now().date().isoformat()


def parse_date(value: object, field: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ActionError("bad_request", f"{field} must use the format YYYY-MM-DD.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ActionError("bad_request", f"{field} is not a valid date.") from None
    return value


def optional_date(value: object, field: str) -> str:
    return "" if value in ("", None, "none") else parse_date(value, field)


def clean_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ActionError("bad_request", f"{field} is required.")
    value = value.strip()
    if not value or len(value) > limit or any(char in value for char in "\r\n\x00"):
        raise ActionError("bad_request", f"{field} must be 1 to {limit} characters on one line.")
    if (field == "Owner" and " — " in value) or any(marker in value for marker in RESERVED):
        raise ActionError("bad_request", f"{field} contains a separator reserved for registers.")
    return value


def valid_group(slug: str) -> bool:
    return len(slug) <= GROUP_LIMIT and GROUP_RE.fullmatch(slug) is not None


def clean_group(value: object) -> str:
    """A group slug, or '' for none."""
    slug = value.strip() if isinstance(value, str) else None
    if slug is None or (slug and not valid_group(slug)):
        raise ActionError("bad_request", f"Invalid group: lowercase letters, digits and hyphens (ingestion-workshop), {GROUP_LIMIT} characters at most.")
    return slug


def split_group(title: str) -> tuple[str, str]:
    """(title without its trailing `#group/<slug>` tag, slug); the title unchanged and '' when it has none."""
    match = TRAILING_GROUP_RE.search(title)
    if match and len(match.group(1)) <= GROUP_LIMIT:
        return title[:match.start()].rstrip(), match.group(1)
    return title, ""


def clean_title(value: object) -> str:
    title = clean_text(value, "Title", 300)
    if split_group(title)[1]:
        raise ActionError("bad_request", "The title must not end with a #group/… tag: use the Group field (--group).")
    return title


def clean_note(value: object) -> str:
    if not isinstance(value, str):
        raise ActionError("bad_request", "Invalid note.")
    note = value.strip()
    if not note or len(note) > 1000 or note.splitlines() != [note] or "\x00" in note:
        raise ActionError("bad_request", "The note must be 1 to 1000 characters on one line.")
    return note


def word_count(text: str) -> int:
    """Whitespace-separated words, each Markdown link `[label](target)` counting as its label."""
    return len(LINK_RE.sub(r"\1", text).split())


def clean_history(value: object, prefix: str | None) -> str:
    """A history text within the cap; a leading `DD/MM:` equal to ``prefix`` (the entry's `DD/MM: `) is dropped, another is refused.

    ``prefix`` None: the entry has no date, so a leading date is the entry's own and stays."""
    note = clean_note(value)
    while prefix is not None and (lead := HISTORY_LEAD_RE.match(note)):
        written = f"{lead.group(1)}/{lead.group(2)}"
        if f"{written}: " != prefix:
            raise ActionError("bad_request", f"The text starts with the date {written} but the entry is dated {prefix[:5]}: "
                                             "give the date of the event with --date YYYY-MM-DD and leave it out of the text.")
        note = clean_note(note[lead.end():])
    words = word_count(note)
    if words > HISTORY_WORDS:
        raise ActionError("bad_request", f"History entry has {words} words; the cap is {HISTORY_WORDS}. Write one change of state, owner, "
                                         "due date or blocker and link the source once; the detail stays in the source.")
    return note


def clean_subtask(value: object) -> str:
    """A subtask text: one line, at most SUBTASK_WORDS words, no Tasks metadata and no action ID (it inherits its action's)."""
    if not isinstance(value, str):
        raise ActionError("bad_request", "Subtask text is required.")
    text = value.strip()
    if not text or len(text) > 300 or text.splitlines() != [text] or "\x00" in text:
        raise ActionError("bad_request", "A subtask must be 1 to 300 characters on one line.")
    if any(marker in text for marker in RESERVED):
        raise ActionError("bad_request", "A subtask carries no Tasks metadata (📅 ⏳ ➕ ✅ ❌ or a priority): it inherits its action's.")
    if STRONG_ID_RE.search(text):
        raise ActionError("bad_request", "A subtask carries no action ID (**ID**): a step that needs one is an action of its own.")
    words = word_count(text)
    if words > SUBTASK_WORDS:
        raise ActionError("bad_request", f"Subtask has {words} words; the cap is {SUBTASK_WORDS}. Name one step; "
                                         "a step that needs more is an action of its own.")
    return text


def state_of(value: str) -> str:
    key = value if value in STATUS else value.strip().lower()
    if key not in STATE_ALIASES:
        raise ActionError("bad_request", "Invalid status or priority.")
    return STATE_ALIASES[key]


def priority_of(value: str) -> str:
    key = value.strip().lower() if value not in PRIORITY else value
    if key not in PRIORITY_ALIASES:
        raise ActionError("bad_request", "Invalid status or priority.")
    return PRIORITY_ALIASES[key]


# --- Reading -------------------------------------------------------------------------------------


def registers(brain: Path) -> list[Path]:
    """Every action register of the brain, those of the archived projects included (see `live_registers`)."""
    root = (brain / "projects").resolve()
    found = []
    for path in sorted(root.glob("**/state/actions.md")):
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            continue
        found.append(path)
    return found


def live_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    """The parts of a path below `projects/` as they read out of the archive, which sits at the level of what it holds:
    `clients/archive/<client>/…` (a whole client), `clients/<client>/missions/archive/<mission>/…`, `internal/archive/<project>/…`,
    and the earlier places `archive/<project>/…` (an internal project) and `clients/<client>/archive/<mission>/…`.
    A path outside any archive comes back unchanged; so a label, a client or an ID scope reads the same archived or not."""
    found = list(parts)
    if found[:1] == ["archive"]:
        found[0] = "internal"
    if found[:2] in (["clients", "archive"], ["internal", "archive"]):
        del found[1]
    if found[:1] == ["clients"] and len(found) > 2 and found[2] == "archive":
        found[2] = "missions"
    if found[:1] == ["clients"] and len(found) > 3 and found[2:4] == ["missions", "archive"]:
        del found[3]
    return tuple(found)


def in_archived_project(path: Path | str, brain: Path) -> bool:
    """True for a path inside an archived project or client (see `live_parts`), the `archive/` folders themselves included.

    ``path`` is absolute, or relative to ``brain``; a path outside the brain is never archived."""
    path = Path(path)
    try:
        parts = path.relative_to(brain).parts if path.is_absolute() else path.parts
    except ValueError:
        return False
    return len(parts) > 1 and parts[0] == "projects" and live_parts(parts[1:]) != parts[1:]


def archived_root(path: Path, brain: Path) -> Path | None:
    """The archived folder that holds ``path`` (absolute): what `brain-state.py unarchive` brings back, the outermost one."""
    parts = path.relative_to(brain / "projects").parts
    for end in range(1, len(parts) + 1):
        head = parts[:end]
        if head[-1] != "archive" and live_parts(head) != head:
            return brain / "projects" / Path(*head)
    return None


def live_registers(brain: Path) -> list[Path]:
    """The registers of the projects that are not archived: what every listing, view and maintenance command reads."""
    return [path for path in registers(brain) if not in_archived_project(path, brain)]


def archived_error(register: Path, brain: Path, read_option: str | None = None) -> ActionError:
    """The refusal for a project that is archived: how to read it (``read_option``), how to bring it back."""
    root = archived_root(register, brain) or register.parent.parent
    folder = f"{brain.name}/{root.relative_to(brain).as_posix()}"
    read = f"add {read_option} to read it, or " if read_option else ""
    return ActionError("bad_request", f"The project {project_label(register, brain)} is archived ({folder}): {read}unarchive it first "
                                      f"with `uv run tools/brain/brain-state.py unarchive {folder} --write`.")


def archives_of(register: Path) -> list[Path]:
    """The action archives (`actions-archive-YYYY.md`) that sit next to a register."""
    return [path for path in sorted(register.parent.glob("actions-archive-*.md")) if path.is_file() and not path.is_symlink()]


def project_label(register: Path, brain: Path) -> str:
    """`client / mission`, else the project folder name; the same for an archived project (see `live_parts`)."""
    parts = live_parts(register.relative_to(brain / "projects").parts[:-2])
    return f"{parts[1]} / {parts[3]}" if parts[0] == "clients" and len(parts) >= 4 else parts[-1]


def id_scope(register: Path, brain: Path) -> tuple[str, ...]:
    """The folder whose IDs a register shares, as `live_parts` reads it: `clients/<client>` or `internal/<project>`."""
    return live_parts(register.relative_to(brain / "projects").parts)[:2]


def line_version(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]


def parse_action(line: str, register: Path, brain: Path, number: int) -> dict | None:
    match = ACTION_RE.match(line)
    if not match:
        return None
    state, action_id, owner, rest = match.groups()
    closure = CLOSURE_RE.search(rest)
    done = closure.group(1) if closure else ""
    rest = CLOSURE_RE.sub("", rest)
    created = CREATED_RE.search(rest)
    due = DUE_RE.search(rest)
    scheduled = SCHEDULED_RE.search(rest)
    priority = PRIORITY_RE.search(rest)
    title, group = split_group(PRIORITY_RE.sub("", SCHEDULED_RE.sub("", CREATED_RE.sub("", DUE_RE.sub("", rest)))).strip())
    return {
        "id": action_id,
        "state": state,
        "owner": owner.strip(),
        "title": LINK_RE.sub(r"\1", title),
        "raw_title": title,  # without the group tag, which is `group`: both go back to `update` as they are
        "group": group,
        "priority": priority.group(1) if priority else "",
        "created": created.group(1) if created else "",
        "created_at": created.group(1) if created else "",
        "updated_at": created.group(1) if created else "",
        "due": due.group(1) if due else "",
        "scheduled": scheduled.group(1) if scheduled else "",
        "done": done,
        "project": project_label(register, brain),
        "register": register.relative_to(brain).as_posix(),
        "line": number,
        "version": line_version(line),
    }


def last_detail(lines: list[str], index: int) -> int:
    """Index of the last indented line of the action's block (``index`` when it has none)."""
    last = index
    position = index + 1
    while position < len(lines) and (lines[position].startswith("    ") or not lines[position].strip()):
        if lines[position].strip():
            last = position
        position += 1
    return last


def items(lines: list[str], index: int, last: int) -> list[tuple[int, int]]:
    """Line ranges (start, end excluded) of the top-level sub-bullets of the action's block."""
    found = []
    position = index + 1
    while position <= last:
        if not lines[position].startswith("    - "):
            position += 1
            continue
        end = position + 1
        stop = end
        while end <= last and (lines[end].startswith("     ") or not lines[end].strip()):
            end += 1
            if lines[end - 1].strip():
                stop = end
        found.append((position, stop))
        position = stop
    return found


def item_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(line[4:] if line.strip() else "" for line in lines[start:end])


def subtask_of(text: str) -> re.Match | None:
    """The checkbox of a sub-bullet's text (first line, from `item_text`): state and text; None when it is not a subtask."""
    return SUBTASK_RE.match(text.split("\n", 1)[0])


def block_items(lines: list[str], index: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(history, subtasks): the line ranges of the action's top-level sub-bullets, checkboxes apart, each in block order.

    The history list is every other sub-bullet (`source`, `created`… included): its ranks are the history indices."""
    history: list[tuple[int, int]] = []
    subtasks: list[tuple[int, int]] = []
    for start, end in items(lines, index, last_detail(lines, index)):
        (subtasks if subtask_of(item_text(lines, start, end)) else history).append((start, end))
    return history, subtasks


def subtask_info(text: str, number: int) -> dict:
    """A subtask as JSON: its index, its text without the done date, whether it is ticked and the `✅` date ("" when none)."""
    match = subtask_of(text)
    assert match is not None
    rest = (match.group(2) or "").rstrip()
    closed = SUBTASK_DONE_RE.search(rest)
    done = match.group(1) in {"x", "X"}
    return {"index": number, "text": rest[:closed.start()].rstrip() if closed else rest, "done": done,
            "done_on": closed.group(1) if closed and done else ""}


def subtasks_of(lines: list[str], index: int) -> list[dict]:
    return [subtask_info(item_text(lines, start, end), number) for number, (start, end) in enumerate(block_items(lines, index)[1])]


def history_end(lines: list[str], index: int) -> int:
    """Where a new history entry goes: the end of the block, or right after the last other sub-bullet when subtasks end it."""
    last = last_detail(lines, index)
    history, subtasks = block_items(lines, index)
    if subtasks and history and subtasks[-1][0] > history[-1][0]:
        return history[-1][1]
    return last + 1


def block_version(lines: list[str], index: int) -> str:
    """The `details_version` of the action at ``index``: hash of its line and its block."""
    return hashlib.sha256("\n".join([lines[index], *lines[index + 1:last_detail(lines, index) + 1]]).encode("utf-8")).hexdigest()[:16]


def stamp_of(lines: list[str], index: int, pattern: re.Pattern, fallback: str) -> str:
    for start, end in items(lines, index, last_detail(lines, index)):
        match = pattern.match(item_text(lines, start, end))
        if match:
            return f"{match.group(1)} {match.group(2)}" if match.group(2) else match.group(1)
    return fallback


def with_stamps(action: dict, lines: list[str], index: int) -> dict:
    action["created_at"] = stamp_of(lines, index, CREATED_AT_RE, action["created"])
    action["updated_at"] = stamp_of(lines, index, UPDATED_AT_RE, action["created_at"])
    return action


def updated_item(lines: list[str], index: int) -> tuple[int, int] | None:
    """Line range (start, end excluded) of the `updated:` sub-bullet of the action at ``index``, None when it has none."""
    for start, end in items(lines, index, last_detail(lines, index)):
        if UPDATED_AT_RE.match(item_text(lines, start, end)):
            return start, end
    return None


def stamp_updated(lines: list[str], index: int, moment: str) -> None:
    """Set the `updated:` sub-bullet of the action at ``index`` (after `created:` when it is added).

    Low level: `refresh_updated` decides whether a change deserves a new stamp."""
    stamp = f"    - updated: {moment}"
    current = updated_item(lines, index)
    if current:
        lines[current[0]:current[1]] = [stamp]
        return
    found = items(lines, index, last_detail(lines, index))
    after = next((end for start, end in found if CREATED_AT_RE.match(item_text(lines, start, end))), None)
    if after is None:
        after = next((end for start, end in found if SOURCE_RE.match(item_text(lines, start, end))), last_detail(lines, index) + 1)
    lines.insert(after, stamp)


def block_signature(lines: list[str], index: int) -> list[str]:
    """The action line and its sub-bullets without the `updated:` one and without trailing whitespace.

    Two versions of an action with the same signature are the same action: only `updated:` may differ."""
    skip = updated_item(lines, index)
    last = last_detail(lines, index)
    return [line.rstrip() for position, line in enumerate(lines[index:last + 1], index)
            if not (skip and skip[0] <= position < skip[1])]


def synced_block(register: Path, action_id: str) -> list[str] | None:
    """The block of ``action_id`` at the last Git synchronization point, wherever it sits in ``register``.

    The synchronization point is the merge base of HEAD and its upstream: it stays behind unsent local commits and is
    still the last common state when the upstream moved after a fetch. HEAD is the fallback when no upstream is known.
    None is returned quietly when Git cannot read the reference, the file or exactly one matching action."""
    try:
        common = subprocess.run(["git", "-C", str(register.parent), "merge-base", "HEAD", "@{upstream}"],
                                capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        reference = common.stdout.decode("ascii").strip() if common.returncode == 0 else "HEAD"
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", reference):
            reference = "HEAD"
        shown = subprocess.run(["git", "-C", str(register.parent), "show", f"{reference}:./{register.name}"],
                               capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        if shown.returncode != 0:
            return None
        snapshot = shown.stdout.decode("utf-8").splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    found = [number for number, line in enumerate(snapshot) if (match := ACTION.match(line)) and match.group(2) == action_id]
    if len(found) != 1:
        return None
    return snapshot[found[0]:last_detail(snapshot, found[0]) + 1]


def updated_lines(lines: list[str], index: int) -> list[str]:
    current = updated_item(lines, index)
    return lines[current[0]:current[1]] if current else []


def restore_updated(lines: list[str], index: int, synced: list[str]) -> None:
    """Give the action at ``index`` the `updated:` sub-bullet of ``synced``, its block at the synchronization point.

    Both blocks are the same but for `updated:`, so that sub-bullet goes back to the same place; no line when it had none."""
    current = updated_item(lines, index)
    if current:
        del lines[current[0]:current[1]]
    earlier = updated_item(synced, 0)
    if earlier:
        lines[index + earlier[0]:index + earlier[0]] = synced[earlier[0]:earlier[1]]


def refresh_updated(lines: list[str], index: int, before: list[str], register: Path) -> bool:
    """Settle the `updated:` sub-bullet of the action at ``index`` once a change has been applied to ``lines``.

    ``before`` is `block_signature(lines, index)` taken before the change; ``register`` is the file the action is
    written to. The stamp moves only when the action really changed:
    1. the block is the one at the last Git synchronization point: it gets back the `updated:` of that version
       (and loses the line if that version had none), including when this repairs a stamp left dirty by an earlier edit;
    2. otherwise, when the block is as it was before the change, `updated:` stays as it was;
    3. every other change gets the current time.
    Returns whether the `updated:` sub-bullet differs afterwards."""
    previous = updated_lines(lines, index)
    after = block_signature(lines, index)
    match = ACTION.match(lines[index])
    synced = synced_block(register, match.group(2)) if match else None
    if synced is not None and block_signature(synced, 0) == after:
        restore_updated(lines, index, synced)
    elif after != before:
        stamp_updated(lines, index, f"{now():%Y-%m-%d %H:%M}")
    return updated_lines(lines, index) != previous


def load(register: Path, brain: Path) -> list[dict]:
    lines = register.read_text(encoding="utf-8").splitlines()
    found = []
    for index, line in enumerate(lines):
        action = parse_action(line, register, brain, index + 1)
        if action:
            action = with_stamps(action, lines, index)
            subtasks = subtasks_of(lines, index)
            if subtasks:  # only then: an action without subtasks keeps its JSON
                action["subtasks"] = {"done": sum(item["done"] for item in subtasks), "total": len(subtasks)}
            found.append(action)
    return found


def find(brain: Path, action_id: str, archived: bool = False) -> tuple[Path, list[str], int, dict]:
    """The one action with this ID in the registers. ``archived``, for reading only, also looks in their archives when no register holds it.

    Without ``archived`` (every write), an action of an archived project is refused: the project must be unarchived first."""
    def scan(paths: list[Path]) -> list[tuple[Path, list[str], int, dict]]:
        found = []
        for path in paths:
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                action = parse_action(line, path, brain, index + 1)
                if action and action["id"] == action_id:
                    found.append((path, lines, index, with_stamps(action, lines, index)))
        return found

    live = registers(brain)
    found = scan(live)
    if not found and archived:
        found = scan([archive for register in live for archive in archives_of(register)])
    if len(found) != 1:
        raise ActionError("not_found" if not found else "conflict", "Action not found or duplicate ID.")
    if not archived and in_archived_project(found[0][0], brain):
        raise archived_error(found[0][0], brain)
    return found[0]


def details(brain: Path, action_id: str) -> dict:
    """An action with its sub-bullets; an archived one too, flagged ``archived`` (every write still refuses it as not found).

    `notes` is the history (every sub-bullet but the subtasks), indexed as `history edit` and `remove` address it;
    `subtasks`, `subtasks_done` and `subtasks_total` come only when the action has subtasks."""
    path, lines, index, action = find(brain, action_id, archived=True)
    last = last_detail(lines, index)
    block = lines[index + 1:last + 1]
    while block and not block[0].strip():
        block.pop(0)
    history, _ = block_items(lines, index)
    notes = [{"index": number, "text": (text := item_text(lines, start, end)), "deletable": not PROTECTED_RE.match(text)}
             for number, (start, end) in enumerate(history)]
    subtasks = subtasks_of(lines, index)
    progress = {"subtasks": subtasks, "subtasks_done": sum(item["done"] for item in subtasks), "subtasks_total": len(subtasks)} if subtasks else {}
    return {**action, "details": [line[4:] if line.strip() else "" for line in block], "notes": notes, **progress,
            "details_version": block_version(lines, index), **({"archived": True} if path.name != "actions.md" else {}),
            **({"project_archived": True} if in_archived_project(path, brain) else {})}


def show_text(brain: Path, action_id: str, last: int = 3) -> str:
    """An action as compact text, each piece once: its line as written, its dates, its source, its history, where it is.

    The history is every sub-bullet but the subtasks, `source`, `due`, `created` and `updated`; ``last`` keeps the latest
    entries (0: all). The subtasks, all of them as written, come between the dates and the source.
    An archived action is read as `details` reads it and flagged on the last line (`file:line`, from the Work root)."""
    if last < 0:
        raise ActionError("bad_request", "--last must be zero or positive.")
    path, lines, index, action = find(brain, action_id, archived=True)
    history_items, subtask_items = block_items(lines, index)
    notes = [item_text(lines, start, end) for start, end in history_items]
    subtasks = subtasks_of(lines, index)
    checklist = ([f"subtasks, {sum(item['done'] for item in subtasks)} of {len(subtasks)} done:",
                  *(item_text(lines, start, end) for start, end in subtask_items)] if subtasks else [])
    due_note = next((found.group(1).strip(" —–-") for note in notes if (found := DUE_NOTE_RE.match(note))), "")  # `due: —` says nothing
    due = " ".join(part for part in (action["due"], f"({due_note})" if due_note and action["due"] else due_note) if part)
    dates = (("due", due), ("created", action["created_at"]), ("updated", action["updated_at"] if updated_item(lines, index) else ""),
             ("closed", action["done"]))
    history = [note for note in notes if not PROTECTED_RE.match(note) and not DUE_NOTE_RE.match(note)]
    kept = history[-last:] if 0 < last < len(history) else history
    count = (f"history, last {len(kept)} of {len(history)}:" if len(kept) < len(history)
             else f"history, {len(history)} entr{'y' if len(history) == 1 else 'ies'}:" if history else "history: none")
    where = (f"{display(path)}:{index + 1}" + (" (archived)" if path.name != "actions.md" else "")
             + (" (archived project)" if in_archived_project(path, brain) else ""))
    return "\n".join([lines[index].rstrip(), " · ".join([action["project"], *(f"{label} {value}" for label, value in dates if value)]),
                      *checklist, *(note for note in notes if SOURCE_RE.match(note)), count, *kept, where])


def matching_registers(brain: Path, project: str) -> list[Path]:
    """The registers named by ``project``: path (brain- or Work-relative), project folder, `client/mission` or label."""
    wanted = project.strip().strip("/")
    if not wanted:
        raise ActionError("bad_request", "Invalid project.")
    matches = []
    for path in registers(brain):
        relative = path.relative_to(brain).as_posix()
        folder = path.parent.parent.relative_to(brain / "projects").parts
        live = live_parts(folder)
        short = f"{live[1]}/{live[3]}" if live[0] == "clients" and len(live) >= 4 else live[-1]
        project_dir = path.parent.parent.relative_to(brain).as_posix()
        candidates = {relative, f"{brain.name}/{relative}", project_dir, f"{brain.name}/{project_dir}",
                      "/".join(folder), short, project_label(path, brain)}
        if wanted in candidates:
            matches.append(path)
    return matches


def resolve_register(brain: Path, project: str, archived: bool = False, read_option: str | None = None) -> Path:
    """A register from its path (brain- or Work-relative), its project folder, `client/mission` or label.

    An archived project resolves only with ``archived`` (a read); otherwise it is refused with the way to bring it back,
    and ``read_option`` (`--archived`) when the command can read it. A live project wins over an archived one of the same name."""
    matches = matching_registers(brain, project)
    live = [path for path in matches if not in_archived_project(path, brain)]
    if not archived:
        if not live and matches:
            raise archived_error(matches[0], brain, read_option)
        matches = live
    elif live:
        matches = live
    if len(matches) != 1:
        raise ActionError("bad_request", "Unknown project." if not matches else "Ambiguous project: give the register path.")
    return matches[0]


# --- Writing -------------------------------------------------------------------------------------


def action_line(action_id: str, title: str, owner: str, state: str, priority: str, created: str, due: str, scheduled: str, closure: str,
                group: str = "") -> str:
    return (f"- [{state}] **{action_id}** — {owner} — {title}"
            + (f" #group/{group}" if group else "")
            + (f" {priority}" if priority else "")
            + (f" ➕ {created}" if created else "")
            + (f" 📅 {due}" if due else "")
            + (f" ⏳ {scheduled}" if scheduled else "")
            + (f" {'✅' if state == 'x' else '❌'} {closure}" if state in {"x", "-"} and closure else ""))


def atomic_write(path: Path, data: bytes) -> None:
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


def write(path: Path, existing: str, lines: list[str], dry_run: bool) -> str:
    text = "\n".join(lines) + ("\n" if existing.endswith("\n") else "")
    if path.read_text(encoding="utf-8") != existing:
        raise ActionError("conflict", "The register changed. Refresh before retrying.")
    if not dry_run and text != existing:  # a write that changes nothing leaves the file alone
        atomic_write(path, text.encode("utf-8"))
    return text


def check_versions(brain: Path, action_id: str, line_v: str | None, details_v: str | None) -> None:
    if line_v is not None and find(brain, action_id)[3]["version"] != line_v:
        raise ActionError("conflict", "The action changed in the register. Refresh before retrying.")
    if details_v is not None and details(brain, action_id)["details_version"] != details_v:
        raise ActionError("conflict", "The history changed in the register. Reopen the action before retrying.")


def fallback_prefix(register: Path, lines: list[str]) -> str | None:
    """The ID prefix of a register that holds no action: the one its header reserves, else the single one of its archives."""
    header = next((index for index, line in enumerate(lines) if line.startswith("## ")), len(lines))
    reserved = RESERVED_PREFIX.search("\n".join(lines[:header]))
    if reserved:
        return reserved.group(1)
    archived = {match.group(2).split("-")[0] for archive in archives_of(register)
                for match in map(ACTION_RE.match, archive.read_text(encoding="utf-8").splitlines()) if match}
    return next(iter(archived)) if len(archived) == 1 else None


def next_id(brain: Path, register: Path, lines: list[str], prefix: str | None) -> str:
    own = {match.group(2).split("-")[0] for match in map(ACTION_RE.match, lines) if match}
    if prefix:
        prefix = prefix.strip().upper()
        if not re.fullmatch(r"[A-Z]{2,5}", prefix) or (own and own != {prefix}):
            raise ActionError("bad_request", "Invalid ID prefix for this register.")
    elif len(own) == 1:
        prefix = next(iter(own))
    elif not own and (fallback := fallback_prefix(register, lines)):
        prefix = fallback
    else:
        raise ActionError("conflict", "Set an ID prefix in the register before creating actions.")
    axis, name = id_scope(register, brain)
    places = [Path(axis, name), Path(axis, "archive", name)] + ([Path("archive", name)] if axis == "internal" else [])
    highest = 0
    for scope in [brain / "projects" / place for place in places]:  # the live folder and its archived place: IDs are never reused
        if not scope.is_dir() or scope.is_symlink():
            continue
        for md in scope.rglob("*.md"):
            if md.is_symlink() or not md.resolve().is_relative_to(scope.resolve()):
                continue
            for match in ID_RE.finditer(md.read_text(encoding="utf-8")):
                if match.group(1) == prefix:
                    highest = max(highest, int(match.group(2)))
    if highest >= 999:
        raise ActionError("conflict", "The ID series is exhausted.")
    return f"{prefix}-{highest + 1:03d}"


def create(brain: Path, project: str, title: str, owner: str, source: str, state: str = " ", priority: str = "",
           due: str = "", scheduled: str = "", due_note: str = "", prefix: str | None = None, dry_run: bool = False,
           group: str = "") -> dict:
    path = resolve_register(brain, project)
    title = clean_title(title)
    group = clean_group(group)
    owner = clean_text(owner, "Owner", 120)
    source = clean_note(source)
    state, priority = state_of(state), priority_of(priority)
    if state not in {" ", "/", "w"}:
        raise ActionError("bad_request", "A new action must be to do, in progress or waiting.")
    due, scheduled = optional_date(due, "Due date"), optional_date(scheduled, "Scheduled date")
    existing = path.read_text(encoding="utf-8")
    lines = existing.splitlines()
    action_id = next_id(brain, path, lines, prefix)
    moment = now()
    block = [action_line(action_id, title, owner, state, priority, moment.date().isoformat(), due, scheduled, "", group)]
    if due_note:
        block.append(f"    - due: {clean_note(due_note)}")
    block += [f"    - source: {source}", f"    - created: {moment:%Y-%m-%d %H:%M}", f"    - updated: {moment:%Y-%m-%d %H:%M}"]
    bounds = section_bounds(lines, "open")
    if bounds:
        heading, end = bounds
        found = parse_blocks(lines[heading:end])
        insert = heading + found[-1].end if found else heading + 1
    else:
        insert = next((index for index, line in enumerate(lines) if line.startswith("## ") and section_key(line[3:]) == "done"), len(lines))
        while insert > 0 and not lines[insert - 1].strip():
            insert -= 1
    lines[insert:insert] = block
    if insert + len(block) < len(lines) and lines[insert + len(block)].startswith("## "):
        lines.insert(insert + len(block), "")
    write(path, existing, lines, dry_run)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": f"creation of {action_id}",
            "line": block[0], "created_at": f"{moment:%Y-%m-%d %H:%M}", "dry_run": dry_run}


def update(brain: Path, action_id: str, *, title: str | None = None, owner: str | None = None, state: str | None = None,
           priority: str | None = None, due: str | None = None, scheduled: str | None = None, closed_on: str | None = None,
           expect_version: str | None = None, dry_run: bool = False, group: str | None = None) -> dict:
    path, lines, index, current = find(brain, action_id)
    if expect_version is not None and current["version"] != expect_version:
        raise ActionError("conflict", "The action changed in the register. Refresh before retrying.")
    existing = path.read_text(encoding="utf-8")
    if existing.splitlines() != lines:
        raise ActionError("conflict", "The register changed. Refresh before retrying.")
    new = {
        "title": current["raw_title"] if title is None else clean_title(title),
        "owner": current["owner"] if owner is None else clean_text(owner, "Owner", 120),
        "state": current["state"] if state is None else state_of(state),
        "priority": current["priority"] if priority is None else priority_of(priority),
        "due": current["due"] if due is None else optional_date(due, "Due date"),
        "scheduled": current["scheduled"] if scheduled is None else optional_date(scheduled, "Scheduled date"),
        "group": current["group"] if group is None else clean_group(group),
    }
    if closed_on is not None:
        closed_on = parse_date(closed_on, "Closing date")
        if new["state"] not in {"x", "-"}:
            raise ActionError("bad_request", "A closing date requires the state x or -.")
    if new["state"] == current["state"]:
        closure = closed_on or current["done"]
    else:
        closure = closed_on or today()
    still_open = sum(not item["done"] for item in subtasks_of(lines, index))
    warnings = [f"{still_open} subtask{'s' if still_open > 1 else ''} of {action_id} still open, left unticked."] \
        if still_open and new["state"] in {"x", "-"} and new["state"] != current["state"] else []
    before = block_signature(lines, index)
    lines[index] = action_line(action_id, new["title"], new["owner"], new["state"], new["priority"], current["created"],
                               new["due"], new["scheduled"], closure, new["group"])
    updated_changed = refresh_updated(lines, index, before, path)
    text = "\n".join(lines) + ("\n" if existing.endswith("\n") else "")
    swept = sweep_text(text, now().date(), path, only={action_id}).output
    if swept is not None:
        lines = swept.split("\n")
        if existing.endswith("\n") and lines and lines[-1] == "":
            lines.pop()
    keys = ("title", "owner", "priority", "due", "scheduled", "group")
    only_state = new["state"] != current["state"] and all(new[k] == (current["raw_title"] if k == "title" else current[k]) for k in keys)
    label = f"status of {action_id} → {STATE_LABELS[new['state']]}" if only_state else f"edit of {action_id}"
    write(path, existing, lines, dry_run)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": label,
            "line": next(line for line in lines if f"**{action_id}**" in line and ACTION_RE.match(line)),
            "updated_changed": updated_changed, "dry_run": dry_run, **({"warnings": warnings} if warnings else {})}


def add_history(brain: Path, action_id: str, text: str, when: str | None = None, expect_details_version: str | None = None,
                dry_run: bool = False) -> dict:
    """Append a dated history entry after the last one (never among the subtasks); an exact duplicate writes nothing."""
    day = parse_date(when, "Date") if when else today()
    note = clean_history(text, history_prefix(day))
    check_versions(brain, action_id, None, expect_details_version)
    path, lines, index, _ = find(brain, action_id)
    existing = path.read_text(encoding="utf-8")
    entry = f"- {history_prefix(day)}{note}"
    if any(item_text(lines, start, end).split("\n", 1)[0].rstrip() == entry for start, end in block_items(lines, index)[0]):
        return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": f"note already in {action_id}",
                "updated_changed": False, "unchanged": True, "dry_run": dry_run}
    before = block_signature(lines, index)
    lines.insert(history_end(lines, index), f"    {entry}")
    updated_changed = refresh_updated(lines, index, before, path)
    write(path, existing, lines, dry_run)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": f"note added to {action_id}",
            "updated_changed": updated_changed, "unchanged": False, "dry_run": dry_run}


def remove_history(brain: Path, action_id: str, number: int, expect_text: str | None = None,
                   expect_details_version: str | None = None, dry_run: bool = False) -> dict:
    check_versions(brain, action_id, None, expect_details_version)
    path, lines, index, _ = find(brain, action_id)
    existing = path.read_text(encoding="utf-8")
    found = block_items(lines, index)[0]  # the subtasks are never history
    if not 0 <= number < len(found):
        raise ActionError("bad_request", "Note not found.")
    start, end = found[number]
    text = item_text(lines, start, end)
    if expect_text is not None and text != expect_text:
        raise ActionError("conflict", "The note changed in the register. Reopen the action before retrying.")
    if PROTECTED_RE.match(text):
        raise ActionError("bad_request", "The source, created and updated lines cannot be deleted.")
    before = block_signature(lines, index)
    del lines[start:end]
    while start < len(lines) and not lines[start].strip() and not lines[start - 1].strip():
        del lines[start]
    updated_changed = refresh_updated(lines, index, before, path)
    write(path, existing, lines, dry_run)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": f"note deleted from {action_id}",
            "removed": text, "updated_changed": updated_changed, "dry_run": dry_run}


def edit_history(brain: Path, action_id: str, number: int, text: str, when: str | None = None, expect_text: str | None = None,
                 expect_details_version: str | None = None, dry_run: bool = False) -> dict:
    """Rewrite one history entry (its first line); its date is kept unless ``when`` is given, its sub-lines stay."""
    clean_note(text)
    day = parse_date(when, "Date") if when else None
    check_versions(brain, action_id, None, expect_details_version)
    path, lines, index, _ = find(brain, action_id)
    existing = path.read_text(encoding="utf-8")
    found = block_items(lines, index)[0]  # the subtasks are never history
    if not 0 <= number < len(found):
        raise ActionError("bad_request", "Note not found.")
    start, end = found[number]
    current = item_text(lines, start, end)
    if expect_text is not None and current != expect_text:
        raise ActionError("conflict", "The note changed in the register. Reopen the action before retrying.")
    if PROTECTED_RE.match(current):
        raise ActionError("bad_request", "The source, created and updated lines cannot be edited.")
    dated = HISTORY_DATE_RE.match(lines[start])
    if day:
        prefix = history_prefix(day)
    else:
        prefix = dated.group(1) if dated else ""
    note = clean_history(text, prefix or None)
    before = block_signature(lines, index)
    lines[start] = f"    - {prefix}{note}"
    updated_changed = refresh_updated(lines, index, before, path)
    write(path, existing, lines, dry_run)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": f"note edited on {action_id}",
            "before": current, "updated_changed": updated_changed, "dry_run": dry_run}


def subtask_line(state: str, text: str, done_on: str = "") -> str:
    return f"    - [{state}] {text}" + (f" ✅ {done_on}" if done_on else "")


def put_subtasks(lines: list[str], index: int, groups: list[list[str]]) -> None:
    """Write the subtasks of the action at ``index``, each with its sub-lines, in order right under the action line.

    They are first taken out wherever they sit, so that a hand-made one placed lower in the block comes back to the top."""
    for start, end in reversed(block_items(lines, index)[1]):
        del lines[start:end]
        while start < len(lines) and not lines[start].strip() and not lines[start - 1].strip():
            del lines[start]
    lines[index + 1:index + 1] = [line for group in groups for line in group]


def change_subtasks(brain: Path, action_id: str, change, expect_details_version: str | None, dry_run: bool) -> dict:
    """Apply ``change`` to the subtasks of an action, then write them back; `updated:` is settled, no history entry is added.

    ``change(groups)`` edits the list of subtasks (each the lines of one sub-bullet) in place and returns (label, index of
    the subtask concerned or None, extra fields of the result)."""
    check_versions(brain, action_id, None, expect_details_version)
    path, lines, index, _ = find(brain, action_id)
    existing = path.read_text(encoding="utf-8")
    groups = [lines[start:end] for start, end in block_items(lines, index)[1]]
    label, focus, extra = change(groups)
    before = block_signature(lines, index)
    put_subtasks(lines, index, groups)
    updated_changed = refresh_updated(lines, index, before, path)
    text = write(path, existing, lines, dry_run)
    subtasks = subtasks_of(lines, index)
    return {"id": action_id, "register": path.relative_to(brain).as_posix(), "label": label,
            **({"index": focus, "subtask": subtasks[focus]} if focus is not None else {}), **extra,
            "subtasks": subtasks, "subtasks_done": sum(item["done"] for item in subtasks), "subtasks_total": len(subtasks),
            "details_version": block_version(lines, index), "updated_changed": updated_changed, "unchanged": text == existing,
            "dry_run": dry_run}


def subtask_at(groups: list[list[str]], number: int) -> dict:
    if not 0 <= number < len(groups):
        raise ActionError("bad_request", "Subtask not found.")
    return subtask_info(item_text(groups[number], 0, len(groups[number])), number)


def add_subtask(brain: Path, action_id: str, text: str, position: int | None = None, expect_details_version: str | None = None,
                dry_run: bool = False) -> dict:
    """A new open subtask at ``position`` (0: first; default: last)."""
    text = clean_subtask(text)

    def change(groups: list[list[str]]) -> tuple:
        if len(groups) >= SUBTASKS_MAX:
            raise ActionError("bad_request", f"An action holds at most {SUBTASKS_MAX} subtasks: split the work into several actions.")
        at = len(groups) if position is None else position
        if not 0 <= at <= len(groups):
            raise ActionError("bad_request", f"The position must be 0 to {len(groups)}.")
        groups.insert(at, [subtask_line(" ", text)])
        return f"subtask added to {action_id}", at, {}
    return change_subtasks(brain, action_id, change, expect_details_version, dry_run)


def toggle_subtask(brain: Path, action_id: str, number: int, done: bool | None = None, expect_details_version: str | None = None,
                   dry_run: bool = False) -> dict:
    """Tick (with today's `✅` date) or untick (dropping it) a subtask; ``done`` forces a state, a subtask already in it is left as is."""
    def change(groups: list[list[str]]) -> tuple:
        current = subtask_at(groups, number)
        target = not current["done"] if done is None else done
        if target != current["done"]:
            groups[number][0] = subtask_line("x", current["text"], today()) if target else subtask_line(" ", current["text"])
        return f"subtask {'ticked' if target else 'unticked'} on {action_id}", number, {}
    return change_subtasks(brain, action_id, change, expect_details_version, dry_run)


def edit_subtask(brain: Path, action_id: str, number: int, text: str, expect_details_version: str | None = None,
                 dry_run: bool = False) -> dict:
    """Rewrite the text of a subtask; its state, its `✅` date and its sub-lines stay."""
    text = clean_subtask(text)

    def change(groups: list[list[str]]) -> tuple:
        current = subtask_at(groups, number)
        state = subtask_of(groups[number][0][4:]).group(1)  # type: ignore[union-attr]
        groups[number][0] = subtask_line(state, text, current["done_on"])
        return f"subtask edited on {action_id}", number, {"before": current["text"]}
    return change_subtasks(brain, action_id, change, expect_details_version, dry_run)


def remove_subtask(brain: Path, action_id: str, number: int, expect_details_version: str | None = None, dry_run: bool = False) -> dict:
    def change(groups: list[list[str]]) -> tuple:
        removed = subtask_at(groups, number)
        del groups[number]
        return f"subtask removed from {action_id}", None, {"removed": removed}
    return change_subtasks(brain, action_id, change, expect_details_version, dry_run)


def move_subtask(brain: Path, action_id: str, number: int, to: int, expect_details_version: str | None = None,
                 dry_run: bool = False) -> dict:
    """Move a subtask so that its index becomes ``to``; the others keep their order."""
    def change(groups: list[list[str]]) -> tuple:
        subtask_at(groups, number)
        if not 0 <= to < len(groups):
            raise ActionError("bad_request", f"The target index must be 0 to {len(groups) - 1}.")
        groups.insert(to, groups.pop(number))
        return f"subtask moved on {action_id}", to, {}
    return change_subtasks(brain, action_id, change, expect_details_version, dry_run)


def relink(text: str, old_dir: Path, new_dir: Path) -> str:
    """Rewrite the relative Markdown links of ``text`` written in ``old_dir`` so they work from ``new_dir``."""
    def fix(match: re.Match) -> str:
        target = match.group(2)
        if re.match(r"^(<|[a-z][a-z0-9+.-]*:|#|/)", target):
            return match.group(0)
        path, sep, anchor = target.partition("#")
        moved = os.path.relpath(os.path.normpath(old_dir / path), new_dir).replace(os.sep, "/")
        return f"{match.group(1)}{moved}{sep}{anchor}{match.group(3)}"
    return MD_LINK_RE.sub(fix, text)


def move(brain: Path, action_id: str, project: str, dry_run: bool = False) -> dict:
    """Move an action, with its block, to another register of the same client (or internal project); ID unchanged."""
    source, lines, index, current = find(brain, action_id)
    target = resolve_register(brain, project)
    if target == source:
        raise ActionError("bad_request", "The action is already in this register.")
    if id_scope(target, brain) != id_scope(source, brain):
        raise ActionError("bad_request", "A move is limited to registers of the same client or project (IDs depend on it).")
    existing, target_existing = source.read_text(encoding="utf-8"), target.read_text(encoding="utf-8")
    end = last_detail(lines, index) + 1
    block = [relink(line, source.parent, target.parent) for line in lines[index:end]]
    while block and not block[-1].strip():
        block.pop()
    day = now()
    target_lines = target_existing.splitlines()
    block.insert(history_end(block, 0), f"    - {history_prefix(day.date().isoformat())}moved from {project_label(source, brain)}")  # exempt from the word cap
    stamp_updated(block, 0, f"{day:%Y-%m-%d %H:%M}")  # always a real change (the history entry above): no need to compare
    del lines[index:end]
    if index and not lines[index - 1].strip():
        while index < len(lines) and not lines[index].strip():
            del lines[index]
    key = STATE_SECTION[current["state"]]
    if section_bounds(target_lines, key) is None:
        raise ActionError("bad_request", f"Section \"{TITLES[key]}\" is missing from the target register.")
    if key == "open":
        insert_open(target_lines, block)
    else:
        insert_block(target_lines, key, block, date.fromisoformat(current["done"]) if current["done"] else day.date())
    if dry_run:
        return {"id": action_id, "from": source.relative_to(brain).as_posix(), "register": target.relative_to(brain).as_posix(),
                "label": f"move of {action_id}", "dry_run": True}
    if source.read_text(encoding="utf-8") != existing or target.read_text(encoding="utf-8") != target_existing:
        raise ActionError("conflict", "The register changed. Refresh before retrying.")
    atomic_write(target, ("\n".join(target_lines) + ("\n" if target_existing.endswith("\n") else "")).encode("utf-8"))
    try:
        atomic_write(source, ("\n".join(lines) + ("\n" if existing.endswith("\n") else "")).encode("utf-8"))
    except OSError:
        atomic_write(target, target_existing.encode("utf-8"))
        raise
    return {"id": action_id, "from": source.relative_to(brain).as_posix(), "register": target.relative_to(brain).as_posix(),
            "label": f"move of {action_id}", "dry_run": False}


def subtask_warnings(lines: list[str], name: str, action_id: str, history: list[tuple[int, int]],
                     subtasks: list[tuple[int, int]]) -> list[str]:
    """`check` warnings about the subtasks of one action: too many, metadata, an ID, a state other than [ ] or [x], misplaced."""
    found = []
    if len(subtasks) > SUBTASKS_MAX:
        found.append(f"{name}:{subtasks[0][0] + 1}: {action_id} has {len(subtasks)} subtasks (at most {SUBTASKS_MAX})")
    for start, end in subtasks:
        match = subtask_of(item_text(lines, start, end))
        assert match is not None
        state, text, where = match.group(1), (match.group(2) or "").rstrip(), f"{name}:{start + 1}"
        if state not in {" ", "x"}:
            found.append(f"{where}: {action_id} subtask in state [{state}] (only [ ] and [x])")
        closed = SUBTASK_DONE_RE.search(text) if state in {"x", "X"} else None
        if any(marker in (text[:closed.start()] if closed else text) for marker in RESERVED):
            found.append(f"{where}: {action_id} subtask with Tasks metadata (it inherits the action's)")
        if STRONG_ID_RE.search(text) and not LOOSE_ACTION_RE.match(lines[start]):  # an indented action line is already an error
            found.append(f"{where}: {action_id} subtask carrying an action ID")
        if history and start > history[0][0]:
            found.append(f"{where}: {action_id} subtask after other sub-bullets (subtasks go right under the action line; "
                         "any `action.py subtask` write puts them back)")
    return found


def check(brain: Path, only: set[Path] | None = None, archived: bool = False) -> dict:
    """Format errors (blocking) and warnings of the action registers; IDs are checked across each client folder.

    The registers of the archived projects are format-checked only with ``archived`` or when ``only`` names them; their
    IDs always count, so that a live action never takes the ID of an archived one."""
    errors: list[str] = []
    warnings: list[str] = []
    seen: dict[tuple, dict[str, str]] = {}
    for path in registers(brain):
        ids_only = in_archived_project(path, brain) and not archived and (only is None or path not in only)
        bucket = seen.setdefault(id_scope(path, brain), {})
        files = [path] + sorted(path.parent.glob("actions-archive-*.md"))
        for file in files:
            lines = file.read_text(encoding="utf-8").splitlines()
            name = file.relative_to(brain).as_posix()
            for number, line in enumerate(lines, 1):
                loose = LOOSE_ACTION_RE.match(line)
                if not loose:
                    continue
                action_id = loose.group(1)
                where = f"{name}:{number}"
                if action_id in bucket:
                    errors.append(f"{where}: {action_id} already present ({bucket[action_id]})")
                else:
                    bucket[action_id] = where
                if file != path or ids_only or (only is not None and path not in only):
                    continue
                match = ACTION_RE.match(line)
                if not match:
                    errors.append(f"{where}: malformed action line (expected `- [state] **ID** — owner — title`)")
                    continue
                for marker, value in re.findall(r"(➕|📅|⏳|✅|❌)\s*(\S+)", line):
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        errors.append(f"{where}: {action_id} invalid {marker} date '{value}'")
                tags = GROUP_TAG_RE.findall(line)
                if any(not valid_group(tag) for tag in tags):
                    warnings.append(f"{where}: {action_id} invalid group slug #group/ (lowercase, digits, hyphens; {GROUP_LIMIT} characters at most)")
                elif len(tags) > 1:
                    warnings.append(f"{where}: {action_id} several #group/ tags (only one expected)")
                elif tags and not parse_action(line, path, brain, number)["group"]:
                    warnings.append(f"{where}: {action_id} tag #group/{tags[0]} not at the end of the title, group ignored")
                state = match.group(1)
                closed = re.search(r"[✅❌]\s*\d{4}-\d{2}-\d{2}", line)
                if state in {"x", "-"} and not closed:
                    warnings.append(f"{where}: {action_id} closed without a ✅/❌ date")
                if state not in {"x", "-"} and closed:
                    errors.append(f"{where}: {action_id} open but carries a closing date")
                if state == "x" and "❌" in line or state == "-" and "✅" in line:
                    errors.append(f"{where}: {action_id} closing mark inconsistent with the state")
                history, subtasks = block_items(lines, number - 1)
                block = [item_text(lines, a, b) for a, b in history]  # a checkbox is a subtask, never a source
                if not any(re.match(r"-\s*(\[?source|\[)", entry, re.IGNORECASE) for entry in block):
                    warnings.append(f"{where}: {action_id} without a source sub-bullet")
                warnings += subtask_warnings(lines, name, action_id, history, subtasks)
    return {"errors": errors, "warnings": warnings}


def delete(brain: Path, action_id: str, expect_version: str | None = None, expect_details_version: str | None = None,
           dry_run: bool = False) -> dict:
    check_versions(brain, action_id, expect_version, expect_details_version)
    path, lines, index, _ = find(brain, action_id)
    existing = path.read_text(encoding="utf-8")
    del lines[index:last_detail(lines, index) + 1]
    if index and not lines[index - 1].strip():
        while index < len(lines) and not lines[index].strip():
            del lines[index]
        if index == len(lines):
            while lines and not lines[-1].strip():
                lines.pop()
    write(path, existing, lines, dry_run)
    return {"deleted": action_id, "register": path.relative_to(brain).as_posix(), "label": f"deletion of {action_id}", "dry_run": dry_run}


def listing(brain: Path, project: str | None, state: str, owner: str | None, due_before: str | None = None,
            limit: int | None = None, archived: bool = False) -> list[dict]:
    """The actions of one register or of all; ``due_before`` keeps those due strictly before that day (earliest first).

    The archived projects are left out unless ``archived``; their actions then carry `"project_archived": true`."""
    if due_before is not None:
        due_before = parse_date(due_before, "Due date limit")
    if limit is not None and limit < 0:
        raise ActionError("bad_request", "The limit must be zero or positive.")
    if project:
        paths = [resolve_register(brain, project, archived, "--archived")]
    else:
        paths = registers(brain) if archived else live_registers(brain)
    found = [{**action, "project_archived": True} if in_archived_project(path, brain) else action
             for path in paths for action in load(path, brain)]
    if state == "open":
        found = [a for a in found if a["state"] in {" ", "/", "w"}]
    elif state == "closed":
        found = [a for a in found if a["state"] in {"x", "-"}]
    if owner:
        found = [a for a in found if owner.lower() in a["owner"].lower()]
    if due_before is not None:
        found = sorted((a for a in found if a["due"] and a["due"] < due_before), key=lambda a: a["due"])
    return found if limit is None else found[:limit]


# --- Board (formerly tasks-board.py) -------------------------------------------------------------
# Complete read-only view by project: the owner's To do, everyone's In progress and Waiting,
# sorted by ID, then the 15 most recent closures, whoever the owner.

BOARD_DONE = re.compile(r"\s*[✅❌]\s*(\d{4}-\d{2}-\d{2})")
BOARD_LIMIT = 15
BOARD_STATES = ((" ", "To do"), ("/", "In progress"), ("w", "Waiting"))


@dataclass(frozen=True)
class BoardItem:
    state: str
    action_id: str
    owner: str
    title: str
    done: str | None
    register: Path
    line: int
    project: str


def board_owner(brain: Path) -> str:
    name = os.environ.get("BRAIN_OWNER", "").strip()
    config = brain / ".data/doctor.json"
    if not name and config.is_file():
        name = str(json.loads(config.read_text(encoding="utf-8")).get("owner", "")).strip()
    if not name:
        raise SystemExit(f"unknown owner: set BRAIN_OWNER or 'owner' in {brain.name}/.data/doctor.json")
    return name


def with_progress(title: str, subtasks: list[dict]) -> str:
    """``title`` with the subtask progress (` 1/3`) after its words, before its group tag and Tasks metadata; as is without subtasks."""
    if not subtasks:
        return title
    progress = f" {sum(item['done'] for item in subtasks)}/{len(subtasks)}"
    meta = TASKS_META_RE.search(title)
    return title[:meta.start()] + progress + title[meta.start():] if meta else title + progress


def board_load(brain: Path) -> list[BoardItem]:
    found = []
    for register in sorted((brain / "projects").glob("**/state/actions.md")):
        if in_archived_project(register, brain):
            continue
        lines = register.read_text(encoding="utf-8").splitlines()
        for number, text in enumerate(lines, start=1):
            match = re.match(r"^- \[(.)\] \*\*([A-Z]{2,5}-\d{3})\*\* — ([^—]+?) — (.*)$", text)
            if not match:
                continue
            state, action_id, owner, rest = match.groups()
            done = BOARD_DONE.search(rest)
            # Links in a title are relative to the register: keep their text only.
            title = with_progress(LINK_RE.sub(r"\1", BOARD_DONE.sub("", rest)).strip(), subtasks_of(lines, number - 1))
            found.append(BoardItem(state, action_id, owner.strip(), title, done.group(1) if done else None, register, number,
                                   project_label(register, brain)))
    return found


def board_groups(found: list[BoardItem], owner: str) -> tuple[list, list[str], list[BoardItem]]:
    """(projects with their state groups, projects with nothing to show, recent closures)."""
    def shown(a: BoardItem) -> bool:
        return a.state in "/w" or (a.state == " " and owner in a.owner)
    projects, empty = [], []
    for project in sorted({a.project for a in found}):
        listed = [a for a in found if a.project == project and shown(a)]
        groups = [(label, sorted((a for a in listed if a.state == symbol), key=lambda a: a.action_id)) for symbol, label in BOARD_STATES]
        groups = [(label, group) for label, group in groups if group]
        (projects.append((project, groups)) if groups else empty.append(project))
    done = sorted((a for a in found if a.state in "xX-" and a.done), key=lambda a: (a.done, a.action_id), reverse=True)
    return projects, empty, done[:BOARD_LIMIT]


def board_render(found: list[BoardItem], owner: str, base: Path) -> str:
    def item(a: BoardItem, dated: bool = False) -> str:
        target = os.path.relpath(a.register, base).replace(os.sep, "/")
        when = f" — {'cancelled' if a.state == '-' else 'done'} on {a.done}" if dated else ""
        return f"- `[{a.state}]` **{a.action_id}** — {a.owner} — {a.title}{when} — [register]({target}#L{a.line})"

    projects, empty, done = board_groups(found, owner)
    out = ["# Tasks", "", "> Snapshot of the `state/actions.md` registers, generated by `uv run tools/brain/action.py board --write`. Do not edit: change an action's state in its register, then run it again.", ""]
    for project, groups in projects:
        out += [f"## {project} ({sum(len(g) for _, g in groups)})", ""]
        for label, group in groups:
            out += [f"**{label}** ({len(group)})", ""] + [item(a) for a in group] + [""]
    if empty:
        out += ["_Nothing in progress, waiting or to do: " + ", ".join(empty) + "._", ""]
    out += [f"## Recently done ({len(done)})", ""]
    out += [item(a, dated=True) for a in done] if done else ["_None._"]
    out.append("")
    return "\n".join(out)


def board_write(brain: Path, target: Path) -> bool:
    """Write the board to target; return True when its content changed."""
    content = board_render(board_load(brain), board_owner(brain), target.parent)
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return True


def board_watch(brain: Path, target: Path, interval: float) -> None:
    """Rewrite the board whenever a register changes; the VS Code preview follows the file."""
    def signature() -> tuple:
        files = sorted((brain / "projects").glob("**/state/actions.md")) + [brain / ".data/doctor.json"]
        return tuple((str(f), f.stat().st_mtime_ns) for f in files if f.is_file())
    print(f"Watching the registers; board: {os.path.relpath(target, Path.cwd())} (Ctrl+C to stop)", flush=True)
    last = None
    try:
        while True:
            current = signature()
            if current != last:
                if board_write(brain, target):
                    print(f"Board updated ({datetime.now():%H:%M:%S})", flush=True)
                last = current
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def board(args: argparse.Namespace) -> int:
    brain = (args.brain[0] if args.brain else BRAIN).expanduser().resolve()
    if not (brain / "projects").is_dir():
        raise SystemExit(f"brain not found: {brain}")
    if args.watch:
        if not args.write:
            raise SystemExit("--watch needs --write")
        board_watch(brain, Path(args.write).resolve(), interval=1.5)
        return 0
    print(board_render(board_load(brain), board_owner(brain), Path.cwd()))
    if args.write:
        target = Path(args.write).resolve()
        board_write(brain, target)
        print(f"\nWritten: {os.path.relpath(target, Path.cwd())}")
    return 0


# --- Command line --------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, read and edit the actions of the brain's registers (JSON output).")
    parser.add_argument("--brain", action="append", type=Path, metavar="PATH", help="brain to process (default: BRAIN_DIR, else the default brain of Work; repeatable for sweep and archive)")
    sub = parser.add_subparsers(dest="command", required=True)

    def writable(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dry-run", action="store_true", help="print the result, write nothing")

    p = sub.add_parser("list", help="list the actions")
    p.add_argument("--project", help="register, project folder, client/mission or label")
    p.add_argument("--state", choices=("open", "closed", "all"), default="open")
    p.add_argument("--owner")
    p.add_argument("--due-before", metavar="YYYY-MM-DD", help="only the actions due strictly before that day, earliest first (no due date: left out)")
    p.add_argument("--limit", type=int, metavar="N", help="at most N actions")
    p.add_argument("--table", action="store_true", help="one line per action instead of JSON")
    p.add_argument("--archived", action="store_true",
                   help="also list the archived projects (left out by default); --project may then name one")

    p = sub.add_parser("board", help="complete view by project, for the terminal or a Markdown preview (read-only)")
    p.add_argument("--write", nargs="?", const=str(WORK / "agents/tasks-board.md"), metavar="PATH",
                   help="also write the board to PATH (default: agents/tasks-board.md)")
    p.add_argument("--watch", action="store_true", help="with --write: keep the file up to date when the registers change")

    p = sub.add_parser("show", help="show an action and its history")
    p.add_argument("id")
    p.add_argument("--text", action="store_true",
                   help="compact plain text instead of JSON: the line as written, its dates, the source, the latest history entries, file:line")
    p.add_argument("--last", type=int, metavar="N", help="with --text: history entries shown, the latest ones (default 3, 0 for all)")

    p = sub.add_parser("create", help="create an action at the end of the Open section")
    p.add_argument("--project", required=True, help="register, project folder, client/mission or label")
    p.add_argument("--title", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--source", required=True, help="text of the source sub-bullet (Markdown link relative to the register)")
    p.add_argument("--state", default=" ", help="todo, in-progress or waiting (default: todo)")
    p.add_argument("--priority", default="", help="high, medium, low or normal")
    p.add_argument("--due", default="", help="precise due date YYYY-MM-DD")
    p.add_argument("--scheduled", default="", help="chosen work date YYYY-MM-DD")
    p.add_argument("--due-note", default="", help="qualified due date, as a sub-bullet ('before…')")
    p.add_argument("--group", default="", help="task group: lowercase-and-hyphens slug, 40 characters at most, written #group/<slug>")
    p.add_argument("--prefix", help="ID prefix, only for a register that is still empty")
    writable(p)

    p = sub.add_parser("update", help="change the fields of an action (only those given)")
    p.add_argument("id")
    for name in ("title", "owner", "state", "priority", "due", "scheduled", "group"):
        p.add_argument(f"--{name}", help="empty value clears a date" if name in {"due", "scheduled"}
                       else "group slug (#group/<slug>), empty value removes it; absent: unchanged" if name == "group" else None)
    p.add_argument("--closed-on", help="date of the closing evidence YYYY-MM-DD (default: today)")
    p.add_argument("--expect-version")
    writable(p)

    p = sub.add_parser("history", help="add, edit or remove a history entry")
    hist = p.add_subparsers(dest="operation", required=True)
    h = hist.add_parser("add")
    h.add_argument("id")
    h.add_argument("--text", required=True)
    h.add_argument("--date", help="date of the event YYYY-MM-DD (default: today)")
    h.add_argument("--expect-details-version")
    writable(h)
    h = hist.add_parser("edit")
    h.add_argument("id")
    h.add_argument("--index", type=int, required=True, help="rank of the sub-bullet (see show)")
    h.add_argument("--text", required=True, help="new text (the existing DD/MM date is kept)")
    h.add_argument("--date", help="new date of the entry YYYY-MM-DD")
    h.add_argument("--expect-text")
    h.add_argument("--expect-details-version")
    writable(h)
    h = hist.add_parser("remove")
    h.add_argument("id")
    h.add_argument("--index", type=int, required=True, help="rank of the sub-bullet (see show)")
    h.add_argument("--expect-text")
    h.add_argument("--expect-details-version")
    writable(h)

    p = sub.add_parser("subtask", help="add, tick, edit, remove or move a subtask (a step of the action's checklist)")
    steps = p.add_subparsers(dest="operation", required=True)
    index_help = "index of the subtask, from 0 (the `index` of `subtasks` in show)"
    for name, text in (("add", "append an open subtask (or insert it at --position)"), ("toggle", "tick or untick a subtask"),
                       ("edit", "rewrite the text of a subtask"), ("remove", "remove a subtask"), ("move", "move a subtask to index --to")):
        s = steps.add_parser(name, help=text)
        s.add_argument("id")
        if name != "add":
            s.add_argument("--index", type=int, required=True, help=index_help)
        if name in {"add", "edit"}:
            s.add_argument("--text", required=True, help=f"one line, {SUBTASK_WORDS} words at most, no Tasks metadata, no **ID**")
        if name == "add":
            s.add_argument("--position", type=int, help="index of the new subtask, from 0 (default: after the last one)")
        if name == "toggle":
            state = s.add_mutually_exclusive_group()
            state.add_argument("--done", dest="done", action="store_const", const=True, default=None, help="tick it (no change if ticked)")
            state.add_argument("--undone", dest="done", action="store_const", const=False, help="untick it (no change if open)")
        if name == "move":
            s.add_argument("--to", type=int, required=True, help="its index after the move, from 0")
        s.add_argument("--expect-details-version")
        writable(s)

    for name, text in (("sweep", "put each action under the section of its state (Open, Done, Cancelled)"),
                       ("archive", "move the actions closed for more than --days days to state/actions-archive-YYYY.md")):
        p = sub.add_parser(name, help=text)
        mode = p.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="write nothing (default behavior)")
        mode.add_argument("--write", action="store_true", help="apply the moves")
        mode.add_argument("--check", action="store_true", help="dry run that exits with code 1 when an action has to move (pre-commit)")
        p.add_argument("--register", action="append", type=Path, metavar="PATH", help="limit the processing to these state/actions.md (repeatable)")
        p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"minimum age of the closure for archive (default {DEFAULT_DAYS})")
        p.add_argument("--today", type=parse_day, help="today's date YYYY-MM-DD (default: ARCHIVE_TODAY, else the Europe/Paris date)")
        p.add_argument("--quiet", action="store_true", help="print only the totals (and the errors)")
        if name == "sweep":
            p.add_argument("--archive", action="store_true", help="also archive, after the sweep")

    p = sub.add_parser("move", help="move an action to another register of the same client (ID unchanged)")
    p.add_argument("id")
    p.add_argument("--to", required=True, help="target register: path, folder, client/mission or label")
    writable(p)

    p = sub.add_parser("check", help="check the format of the registers (exit code 1 on error)")
    p.add_argument("--register", action="append", type=Path, metavar="PATH", help="limit the format check to these registers (IDs are still checked across the whole client)")
    p.add_argument("--quiet", action="store_true", help="print only the errors")
    p.add_argument("--archived", action="store_true",
                   help="also check the format of the archived projects' registers (their IDs always count for duplicates)")

    p = sub.add_parser("delete", help="delete an action and its block")
    p.add_argument("id")
    p.add_argument("--expect-version")
    p.add_argument("--expect-details-version")
    writable(p)
    return parser


def maintain(args: argparse.Namespace) -> int:
    """`sweep` and `archive`: same report and exit codes as the former manage-action.py."""
    operations = {"sweep": args.command == "sweep", "archive": args.command == "archive" or getattr(args, "archive", False)}
    if args.days < 0:
        print("--days must be zero or positive", file=sys.stderr)
        return 2
    today_ = args.today or (parse_day(os.environ["ARCHIVE_TODAY"]) if os.environ.get("ARCHIVE_TODAY") else paris_today())
    brains = [path.expanduser().resolve() for path in (args.brain or [BRAIN])]
    only_registers = {path.expanduser().resolve() for path in args.register} if args.register else None
    totals = {"sweep": 0, "archive": 0}
    hits = {"sweep": 0, "archive": 0}
    errors = 0
    for brain in brains:
        if not brain.is_dir():
            print(f"ERROR {brain.as_posix()}: brain not found", file=sys.stderr)
            errors += 1
            continue
        for register in registers_of(brain):
            if only_registers is not None and register not in only_registers:
                continue
            name = display(register)
            if in_archived_project(register, brain):  # an archived project is left as it was moved
                if only_registers is not None and not args.quiet:
                    print(f"{name}: skipped, archived project")
                continue
            for operation, runner in (("sweep", run_sweep), ("archive", run_archive)):
                if not operations[operation]:
                    continue
                count, failed = runner(register, name, today_, args)
                totals[operation] += count
                hits[operation] += 1 if count else 0
                errors += failed
                if failed:
                    break  # a register in error is left alone by the next operation
    verb = "moved" if args.write else "to move"
    for operation, label in (("sweep", "sweep"), ("archive", "archive")):
        if operations[operation]:
            print(f"Total {label}: {totals[operation]} action(s) {verb} in {hits[operation]} register(s)")
    pending = any(totals.values())
    if args.check and pending:
        print(f"Misfiled actions: run `uv run tools/brain/action.py {args.command} --write` (then stage again).")
    elif not args.write and pending:
        print("(dry run: nothing is written, run again with --write)")
    if errors:
        print(f"{errors} error(s)")
    return 1 if errors or (args.check and pending) else 0


def run(args: argparse.Namespace) -> object:
    brain = (args.brain[0] if args.brain else BRAIN).expanduser().resolve()
    if not (brain / "projects").is_dir():
        raise ActionError("not_found", f"Registers not found under {brain / 'projects'}")
    if args.command == "list":
        return listing(brain, args.project, args.state, args.owner, args.due_before, args.limit, args.archived)
    if args.command == "show":
        if args.last is not None and not args.text:
            raise ActionError("bad_request", "--last goes with --text.")
        return show_text(brain, args.id, 3 if args.last is None else args.last) if args.text else details(brain, args.id)
    if args.command == "create":
        return create(brain, args.project, args.title, args.owner, args.source, args.state, args.priority, args.due,
                      args.scheduled, args.due_note, args.prefix, args.dry_run, args.group)
    if args.command == "update":
        return update(brain, args.id, title=args.title, owner=args.owner, state=args.state, priority=args.priority,
                      due=args.due, scheduled=args.scheduled, closed_on=args.closed_on,
                      expect_version=args.expect_version, dry_run=args.dry_run, group=args.group)
    if args.command == "history" and args.operation == "add":
        return add_history(brain, args.id, args.text, args.date, args.expect_details_version, args.dry_run)
    if args.command == "history" and args.operation == "edit":
        return edit_history(brain, args.id, args.index, args.text, args.date, args.expect_text, args.expect_details_version, args.dry_run)
    if args.command == "subtask":
        lock = {"expect_details_version": args.expect_details_version, "dry_run": args.dry_run}
        if args.operation == "add":
            return add_subtask(brain, args.id, args.text, args.position, **lock)
        if args.operation == "toggle":
            return toggle_subtask(brain, args.id, args.index, args.done, **lock)
        if args.operation == "edit":
            return edit_subtask(brain, args.id, args.index, args.text, **lock)
        if args.operation == "remove":
            return remove_subtask(brain, args.id, args.index, **lock)
        return move_subtask(brain, args.id, args.index, args.to, **lock)
    if args.command == "move":
        return move(brain, args.id, args.to, args.dry_run)
    if args.command == "history":
        return remove_history(brain, args.id, args.index, args.expect_text, args.expect_details_version, args.dry_run)
    return delete(brain, args.id, args.expect_version, args.expect_details_version, args.dry_run)


def main() -> int:
    args = build_parser().parse_args()
    if args.command in {"sweep", "archive"}:
        return maintain(args)
    if args.command == "board":
        return board(args)
    if args.command == "check":
        brain = (args.brain[0] if args.brain else BRAIN).expanduser().resolve()
        result = check(brain, {path.expanduser().resolve() for path in args.register} if args.register else None, args.archived)
        for error in result["errors"]:
            print(f"ERROR {error}")
        if not args.quiet:
            for warning in result["warnings"]:
                print(f"WARNING {warning}")
        print(f"Action check: {len(result['errors'])} error(s), {len(result['warnings'])} warning(s)")
        return 1 if result["errors"] else 0
    try:
        result = run(args)
    except ActionError as error:
        print(json.dumps({"error": error.message, "kind": error.kind}, ensure_ascii=False))
        return EXIT[error.kind]
    except (OSError, UnicodeDecodeError) as error:
        print(json.dumps({"error": str(error), "kind": "conflict"}, ensure_ascii=False))
        return EXIT["conflict"]
    if args.command == "list" and args.table:
        for action in result:  # type: ignore[union-attr]
            extra = " ".join(part for part in (f"[group: {action['group']}]" if action["group"] else "", action["priority"],
                                               f"📅 {action['due']}" if action["due"] else "") if part)
            progress = f" {action['subtasks']['done']}/{action['subtasks']['total']}" if "subtasks" in action else ""
            print(f"[{action['state']}] {action['id']} — {action['owner']} — {action['title']}{progress} {extra}".rstrip()
                  + f"  ({action['project']}{', archived' if action.get('project_archived') else ''})")
        return 0
    if args.command == "show" and args.text:
        print(result)
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
