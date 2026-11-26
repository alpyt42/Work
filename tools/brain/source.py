#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["tzdata>=2024.1; sys_platform == 'win32'"]  # zoneinfo has no time zone database of its own on Windows
# ///
"""Check meeting minutes (`type: cr`) against the rules of the `cr-reunion` skill and keep the monthly source index.

Commands (from the Work root, `uv run tools/brain/source.py <command> --help` for details):

    check      FILE… [--brain PATH] [--json]
    index add  FILE [--subject TEXT] [--brain PATH] [--dry-run] [--json]

`check` reads minutes (`sources/YYYY-MM/YYYY-MM-DD-cr-<slug>.md`) and prints one finding per line,

    path:line  error|warning  message

then one summary line per file: `path  info  body N words / cap C (duration D min)`. It exits 1 when
any file has an error. `--json` prints the same as one JSON document. What it checks:

- Front matter: `date`, `time`, `type`, `title`, `participants`, `provenance`, `reliability`,
  `written_by`, and either `client` and `mission`, or `project`. A file whose `type` is not `cr` is
  reported as not being minutes and skipped.
- Body size. Words are the whitespace tokens that hold a letter or a digit; the front matter, HTML
  comments, link targets (the link text stays) and Markdown markers (`#`, `**`, bullets, `>`) do not
  count. The duration comes from `provenance` (`environ 23 min`, `23 minutes`, `about 45 min`,
  `~1 h 10`, `1h10`, `5,5 min`, `90 min`; a clock time after `à` or `at` is not a duration). The cap
  is 50 words per minute up to 30 minutes, then 20 per further minute, never below 250 nor above
  2,000. Over the cap is an error. With no duration the minutes get a warning and only the 2,000 cap
  applies.
- `## Summary` of 35 to 70 words (warning outside; target 40 to 60); `## Key points` bullets of 90
  words at most (error) and 70 (warning).
- Sections: `Summary` and `Key points` are required; `Decisions`, `Actions and follow-up`,
  `To follow`, `To check` and `Details` are allowed, in that order after them; an empty section is an
  error, an unknown `##` section a warning. The template's instruction quote must be gone.
- Tags: a `Decisions` bullet starts with `**Taken**`, `**Rejected**` or `**To confirm**`; an
  `Actions and follow-up` bullet with `**New**`, `**New · <ID>**`, `**New · not tracked**` or
  `**Follow-up · <ID>**` (IDs like `ABC-123`).
- The index: the file is linked from the `index.md` of its folder and the subject of that line (the
  text after the link's ` — `) holds 15 words at most.
- No local path in the body (`/Users/`, `~/`, `C:\\`, `file://`).

`index add` writes the line of a source into the `index.md` of its folder (`sources/YYYY-MM/`):

    - 2026-11-25 · CR · [Title](2026-11-25-cr-slug.md) — subject of 15 words at most

The line is built from the front matter (`date`, `type`, `title`) and `--subject`. Its style follows
the majority of the lines already in that index: the type label in capitals (`CR`) or lowercase
(the lines of the same type first), a link text with or without the `YYYY-MM-DD — ` prefix, and the
separators. With no line yet, the template's format applies (`CR`, no prefix). The line goes in date
order; for the same date, in the order of the `time` of the listed files when their front matter has
one, else after the lines of that date. A file already listed is refused (exit 4). A missing
`index.md` is created from `kit/brain/templates/_SOURCES-INDEX-TEMPLATE.md`. `--dry-run` prints the
line and its position without writing; the write is atomic. Output is JSON on stdout.

Relative file paths are looked up from the current folder, then from Work, then from the brain.
Exit codes: 0 done, 1 `check` found an error, 2 invalid request, 3 not found, 4 conflict.
`--brain PATH` or BRAIN_DIR selects another brain.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_ACTION = Path(__file__).resolve().with_name("action.py")
action = sys.modules.get("brain_action")
if action is None:
    _spec = importlib.util.spec_from_file_location("brain_action", _ACTION)
    assert _spec and _spec.loader
    action = importlib.util.module_from_spec(_spec)
    sys.modules["brain_action"] = action
    _spec.loader.exec_module(action)

ActionError = action.ActionError
EXIT = action.EXIT

MAX_CAP = 2000
MIN_CAP = 250
SUMMARY_RANGE = (35, 70)
BULLET_ERROR = 90
BULLET_WARNING = 70
SUBJECT_WORDS = 15
REQUIRED_KEYS = ("date", "time", "type", "title", "participants", "provenance", "reliability", "written_by")
SECTIONS = ("Summary", "Key points", "Decisions", "Actions and follow-up", "To follow", "To check", "Details")
REQUIRED_SECTIONS = ("Summary", "Key points")
DECISION_TAG = re.compile(r"\*\*(?:Taken|Rejected|To confirm)\*\*")
ACTION_TAG = re.compile(r"\*\*(?:New|New · [A-Z][A-Z0-9]*-\d+|New · not tracked|Follow-up · [A-Z][A-Z0-9]*-\d+)\*\*")
LOCAL_PATH = re.compile(r"/Users/|(?<![\w.])~/|\b[A-Za-z]:\\|file://")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
ENTRY = re.compile(r"^- (\d{4}-\d{2}-\d{2}) ([·|—–-]) (\S+) [·|—–-] \[((?:\\.|[^\]])*)\]\(([^)]*)\)(?:\s+([—–-])\s+(.*))?\s*$")
INDEX_TEMPLATE = "kit/brain/templates/_SOURCES-INDEX-TEMPLATE.md"
INDEX_FALLBACK = (
    "# Sources — YYYY-MM — <mission>\n\n[Back to the mission](../../<mission>.md)\n\n"
)

# --- Reading ---------------------------------------------------------------------------------------


def split_front_matter(text: str) -> tuple[dict[str, str] | None, int]:
    """The front matter as a flat dict of raw values and the number of lines it takes (0 when none)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, 0
    data: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return data, number
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if match:
            data[match.group(1)] = match.group(2)
    return None, 0


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def blank_comments(text: str) -> str:
    """HTML comments replaced by spaces, newlines kept so that line numbers stay valid."""
    return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)


def count_words(text: str) -> int:
    """Whitespace tokens with a letter or a digit; link targets and HTML comments do not count."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<(?:https?|file)://[^>]*>", " ", text)
    return sum(1 for token in text.split() if any(ch.isalnum() for ch in token))


_HOURS = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(?:h|heures?|hours?|hrs?)(?![a-zà-ÿ])(?:\s*(\d{1,2})(?!\s*[h\d]))?", re.IGNORECASE)
_MINUTES = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(?:minutes?|min|mn)(?![a-zà-ÿ])", re.IGNORECASE)
_APPROX_WORD = r"(?:environ|about|approx\w*|circa|~|c\.)"
# A clock time follows a time preposition, possibly with an approximation word (`à environ 11h30`).
_CLOCK = re.compile(
    r"(?:^|[^\w])(?:à|at|vers|from|until|jusqu['’]à)\s*(?:" + _APPROX_WORD + r"\s*)?$|@\s*$", re.IGNORECASE
)
_RANGE_BEFORE = re.compile(r"\d\s*(?:h|:)\s*\d{0,2}\s*(?:[-–—]|à|to|au)\s*(?:" + _APPROX_WORD + r"\s*)?$", re.IGNORECASE)
_RANGE_AFTER = re.compile(r"\s*(?:[-–—]|à|to|au)\s*(?:" + _APPROX_WORD + r"\s*)?\d{1,2}\s*[h:]", re.IGNORECASE)
_APPROX = re.compile(r"(?:environ|about|approx\w*|circa|~|durée|duration|c\.)\s*$", re.IGNORECASE)


def _is_clock(text: str, match: re.Match[str]) -> bool:
    """An `HhMM` after a time preposition or inside a range of clock times is a time of day."""
    before = text[: match.start()]
    return bool(_CLOCK.search(before) or _RANGE_BEFORE.search(before) or _RANGE_AFTER.match(text, match.end()))


def parse_duration(provenance: str) -> float | None:
    """Minutes in a provenance string, or None.

    An explicit `N min` count wins; otherwise an hours expression (`1 h 10`) that is not a clock
    time (after `à`/`at`/`vers`, or in a range such as `14h00-14h20`). An approximation word or
    `durée` marks the preferred candidate.
    """
    hours_found: list[tuple[int, float, bool]] = []
    minutes_found: list[tuple[int, float, bool]] = []
    spans: list[tuple[int, int]] = []
    for match in _HOURS.finditer(provenance):
        spans.append(match.span())
        if _is_clock(provenance, match):
            continue
        hours = float(match.group(1).replace(",", "."))
        minutes = float(match.group(2)) if match.group(2) else 0.0
        hours_found.append((match.start(), hours * 60 + minutes, bool(_APPROX.search(provenance[: match.start()]))))
    for match in _MINUTES.finditer(provenance):
        if any(start <= match.start() < end for start, end in spans):
            continue
        minutes_found.append((match.start(), float(match.group(1).replace(",", ".")), bool(_APPROX.search(provenance[: match.start()]))))
    candidates = sorted(minutes_found or hours_found)
    if not candidates:
        return None
    marked = [c for c in candidates if c[2]]
    return (marked[0] if marked else candidates[-1])[1]


def word_cap(duration: float | None) -> int:
    if duration is None:
        return MAX_CAP
    raw = 50 * min(duration, 30) + 20 * max(duration - 30, 0)
    return int(min(MAX_CAP, max(MIN_CAP, raw)))


def format_minutes(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


# --- Check -----------------------------------------------------------------------------------------


@dataclass
class Finding:
    line: int
    severity: str
    message: str


@dataclass
class Report:
    path: str
    findings: list[Finding] = field(default_factory=list)
    words: int | None = None
    cap: int | None = None
    duration: float | None = None

    def add(self, line: int, severity: str, message: str) -> None:
        self.findings.append(Finding(line, severity, message))

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


@dataclass
class Section:
    title: str
    line: int  # 1-based line of the heading
    lines: list[tuple[int, str]]  # (line number, text) of the content


def parse_sections(lines: list[str], offset: int) -> list[Section]:
    """`##` sections of the body (outside code fences); `offset` is the number of front matter lines."""
    sections: list[Section] = []
    fenced = False
    current: Section | None = None
    for index, text in enumerate(lines):
        number = offset + index + 1
        if re.match(r"^\s*(```|~~~)", text):
            fenced = not fenced
        heading = None if fenced else re.match(r"^##\s+(.*?)\s*#*\s*$", text)
        if heading and not text.startswith("###"):
            current = Section(heading.group(1).strip(), number, [])
            sections.append(current)
        elif not fenced and re.match(r"^#\s", text):
            current = None
        elif current is not None:
            current.lines.append((number, text))
    return sections


def bullets(section: Section) -> list[tuple[int, str]]:
    """Top-level bullets of a section: (line, full text with continuation lines and sub-bullets)."""
    result: list[tuple[int, str]] = []
    for number, text in section.lines:
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", text):
            result.append((number, re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", text)))
        elif text.strip() and result and text.startswith((" ", "\t")):
            result[-1] = (result[-1][0], result[-1][1] + " " + text.strip())
    return result


def check_text(text: str, path: str, index_dir: Path | None = None, name: str = "") -> Report:
    """All the findings of one file. `index_dir` and `name` locate it in its monthly index."""
    report = Report(path)
    front, offset = split_front_matter(text)
    if front is None:
        report.add(1, "error", "no front matter")
        front, offset = {}, 0
    kind = unquote(front.get("type", ""))
    if front and kind and kind != "cr":
        report.add(1, "error", f"not minutes (type: {kind}), nothing else checked")
        return report
    for key in REQUIRED_KEYS:
        if not unquote(front.get(key, "")):
            report.add(1, "error", f"front matter: `{key}` is missing")
    if not unquote(front.get("project", "")) and not (unquote(front.get("client", "")) and unquote(front.get("mission", ""))):
        report.add(1, "error", "front matter: `client` and `mission`, or `project`, are required")
    if unquote(front.get("project", "")) and (front.get("client") or front.get("mission")):
        report.add(1, "warning", "front matter: `project` goes with neither `client` nor `mission`")
    check_front_values(report, front, name)
    for key, value in front.items():
        if re.search(r"<[^>]+>|YYYY|HH:MM", value) and key not in ("provenance",):
            report.add(1, "error", f"front matter: `{key}` still holds the template placeholder")

    raw_body = text.split("\n")[offset:]
    body = blank_comments("\n".join(raw_body)).split("\n")
    for number, line in enumerate(body, start=offset + 1):
        if LOCAL_PATH.search(line):
            report.add(number, "error", "local path in the body (cite no path outside Work)")
        if re.match(r"^\s*>\s*Template for\b", line):
            report.add(number, "error", "the template's instruction quote is still there")

    cleaned = "\n".join(body)
    report.words = count_words(cleaned)
    provenance = unquote(front.get("provenance", ""))
    report.duration = parse_duration(provenance) if provenance else None
    report.cap = word_cap(report.duration)
    if report.duration is None:
        report.add(1, "warning", "no duration in `provenance`: only the 2,000-word cap is checked")
    if report.words > report.cap:
        detail = "no duration known" if report.duration is None else f"{format_minutes(report.duration)} min of meeting"
        report.add(offset + 1, "error", f"body holds {report.words} words, over the cap of {report.cap} ({detail})")

    check_sections(report, body, offset)
    if index_dir is not None:
        check_index(report, index_dir, name)
    report.findings.sort(key=lambda f: (f.line, 0 if f.severity == "error" else 1))
    return report


def check_front_values(report: Report, front: dict[str, str], name: str) -> None:
    date = unquote(front.get("date", ""))
    if date and not DAY.fullmatch(date):
        report.add(1, "error", f"front matter: `date` {date!r} is not YYYY-MM-DD")
    time = unquote(front.get("time", ""))
    if time and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
        report.add(1, "error", f"front matter: `time` {time!r} is not HH:MM")
    reliability = unquote(front.get("reliability", ""))
    if reliability and reliability not in ("good", "medium", "low"):
        report.add(1, "error", f"front matter: `reliability` {reliability!r} is not good, medium or low")
    participants = front.get("participants", "").strip()
    if participants and not (participants.startswith("[") and participants.endswith("]")):
        report.add(1, "error", "front matter: `participants` must be a list")
    if name and date and DAY.fullmatch(date) and not re.match(rf"{re.escape(date)}-cr-.+\.md$", name):
        report.add(1, "warning", f"file name does not follow `{date}-cr-<slug>.md`")


def check_sections(report: Report, body: list[str], offset: int) -> None:
    sections = parse_sections(body, offset)
    seen: dict[str, Section] = {}
    for section in sections:
        if section.title not in SECTIONS:
            report.add(section.line, "warning", f"unknown section `## {section.title}`")
            continue
        if section.title in seen:
            report.add(section.line, "error", f"section `## {section.title}` appears twice")
            continue
        seen[section.title] = section
    for title in REQUIRED_SECTIONS:
        if title not in seen:
            report.add(offset + 1, "error", f"required section `## {title}` is missing")
    order = [SECTIONS.index(s.title) for s in sections if s.title in SECTIONS and seen.get(s.title) is s]
    if order != sorted(order):
        report.add(seen[SECTIONS[order[0]]].line if order else offset + 1, "error", "sections are not in the template's order: " + ", ".join(SECTIONS))
    for section in seen.values():
        text = "\n".join(t for _, t in section.lines)
        if count_words(text) == 0:
            report.add(section.line, "error", f"section `## {section.title}` is empty")
    summary = seen.get("Summary")
    if summary and count_words("\n".join(t for _, t in summary.lines)):
        words = count_words("\n".join(t for _, t in summary.lines))
        low, high = SUMMARY_RANGE
        if not low <= words <= high:
            report.add(summary.line, "warning", f"summary holds {words} words, outside {low}-{high} (target 40-60)")
    key_points = seen.get("Key points")
    if key_points:
        for number, text in bullets(key_points):
            words = count_words(text)
            if words > BULLET_ERROR:
                report.add(number, "error", f"key point holds {words} words, over {BULLET_ERROR} (split the topic)")
            elif words > BULLET_WARNING:
                report.add(number, "warning", f"key point holds {words} words, over {BULLET_WARNING} (about 60 expected)")
    for title, pattern, expected in (
        ("Decisions", DECISION_TAG, "**Taken**, **Rejected** or **To confirm**"),
        ("Actions and follow-up", ACTION_TAG, "**New**, **New · <ID>**, **New · not tracked** or **Follow-up · <ID>**"),
    ):
        section = seen.get(title)
        if not section:
            continue
        for number, text in bullets(section):
            if not pattern.match(text):
                report.add(number, "error", f"`{title}` bullet must start with {expected}")


def index_entries(index: Path) -> list[tuple[int, re.Match[str]]]:
    return [(n, m) for n, line in enumerate(index.read_text(encoding="utf-8").split("\n"), start=1) if (m := ENTRY.match(line))]


def link_target(target: str) -> str:
    target = target.strip().strip("<>").split("#")[0]
    return target[2:] if target.startswith("./") else target


def check_index(report: Report, folder: Path, name: str) -> None:
    index = folder / "index.md"
    if not index.is_file():
        report.add(1, "error", "no index.md in the folder: the source is not indexed")
        return
    lines = index.read_text(encoding="utf-8").split("\n")
    shown = display(index)
    for number, line in enumerate(lines, start=1):
        for match in re.finditer(r"\]\(([^)]*)\)", line):
            if link_target(match.group(1)) == name:
                subject = re.search(r"\)\s+[—–-]\s+(.*)$", line[match.start():])
                words = count_words(subject.group(1)) if subject else 0
                if words > SUBJECT_WORDS:
                    report.add(1, "error", f"index subject holds {words} words, over {SUBJECT_WORDS} ({shown}:{number})")
                if not subject:
                    report.add(1, "warning", f"index line has no subject ({shown}:{number})")
                return
    report.add(1, "error", f"not linked from {shown}")


# --- Index -----------------------------------------------------------------------------------------


def majority(values: list[object], default: object) -> object:
    counts: dict[object, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return default
    best = max(counts.values())
    leaders = [v for v, c in counts.items() if c == best]
    return default if default in leaders else leaders[0]


def label_style(entries: list[re.Match[str]], kind: str) -> str:
    """`upper` or `lower`, from the lines of the same type, else from every line."""

    def style(match: re.Match[str]) -> str | None:
        label = match.group(3)
        if not any(c.isalpha() for c in label):
            return None
        return "upper" if label.isupper() else "lower" if label.islower() else None

    same = [s for m in entries if m.group(3).lower() == kind.lower() and (s := style(m))]
    pool = same or [s for m in entries if (s := style(m))]
    default = "upper" if kind == "cr" else "lower"
    return str(majority(list(pool), default)) if pool else default


def front_matter_of(path: Path) -> dict[str, str]:
    try:
        front, _ = split_front_matter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}
    return {k: unquote(v) for k, v in (front or {}).items()}


def build_line(entries: list[re.Match[str]], date: str, kind: str, title: str, name: str, subject: str) -> str:
    separator = majority([m.group(2) for m in entries], "·")
    dash = majority([m.group(6) for m in entries if m.group(6)], "—")
    prefixed = [bool(re.match(r"\d{4}-\d{2}-\d{2} [—–-] ", m.group(4))) for m in entries]
    with_prefix = bool(majority(prefixed, False)) if entries else False
    label = kind.upper() if label_style(entries, kind) == "upper" else kind.lower()
    shown = title.replace("[", "\\[").replace("]", "\\]")
    if with_prefix:
        shown = f"{date} — {shown}"
    return f"- {date} {separator} {label} {separator} [{shown}]({name}) {dash} {subject}"


def template_header(month: str, owner: str) -> list[str]:
    try:
        text = (action.WORK / INDEX_TEMPLATE).read_text(encoding="utf-8")
    except OSError:
        text = INDEX_FALLBACK
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith(">") or ENTRY.match(line) or line.startswith("- YYYY"):
            continue
        out.append(line.replace("YYYY-MM", month).replace("<mission>", owner))
    while out and not out[-1].strip():
        out.pop()
    return out


def index_add(file: Path, subject: str, dry_run: bool) -> dict:
    folder = file.parent
    month = folder.name
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ActionError("bad_request", f"{file.name} is not in a `sources/YYYY-MM/` folder")
    front = front_matter_of(file)
    missing = [k for k in ("date", "type", "title") if not front.get(k)]
    if missing:
        raise ActionError("bad_request", "front matter lacks " + ", ".join(f"`{k}`" for k in missing))
    date, kind, title = front["date"], front["type"], front["title"]
    if not DAY.fullmatch(date):
        raise ActionError("bad_request", f"`date` {date!r} is not YYYY-MM-DD")
    if date[:7] != month:
        raise ActionError("bad_request", f"the file is dated {date} but sits in the folder {month}")
    index = folder / "index.md"
    created = not index.is_file()
    text = index.read_text(encoding="utf-8") if not created else ""
    existing = [(n, m) for n, line in enumerate(text.split("\n"), start=1) if (m := ENTRY.match(line))]
    for number, line in enumerate(text.split("\n"), start=1):
        if any(link_target(m.group(1)) == file.name for m in re.finditer(r"\]\(([^)]*)\)", line)):
            raise ActionError("conflict", f"{file.name} is already listed in {display(index)}:{number}")
    subject = " ".join(subject.split())
    if not subject:
        raise ActionError("bad_request", "--subject is required")
    words = count_words(subject)
    if words > SUBJECT_WORDS:
        raise ActionError("bad_request", f"the subject holds {words} words, over {SUBJECT_WORDS}")
    line = build_line([m for _, m in existing], date, kind, title, file.name, subject)

    if created:
        owner = front.get("mission") or front.get("project") or folder.parent.parent.name
        lines = template_header(month, owner)
    else:
        lines = text.rstrip("\n").split("\n")
    entry_rows = [(n - 1, m) for n, m in existing] if not created else []
    time = front.get("time", "")
    insert_at: int | None = None
    for row, match in entry_rows:
        other_date = match.group(1)
        other_time = front_matter_of(folder / link_target(match.group(5))).get("time", "")
        if other_date > date or (other_date == date and time and other_time and other_time > time):
            insert_at = row
            break
    if insert_at is None:
        if entry_rows:
            insert_at = entry_rows[-1][0] + 1
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.append("")
            insert_at = len(lines)
    lines.insert(insert_at, line)
    if not dry_run:
        write_atomic(index, "\n".join(lines) + "\n")
    return {
        "file": display(index),
        "line": line,
        "position": insert_at + 1,
        "created": created,
        "dry_run": dry_run,
        "subject_words": words,
    }


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".source-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


# --- Command line ----------------------------------------------------------------------------------


def display(path: Path) -> str:
    try:
        return path.resolve().relative_to(action.WORK).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_file(value: str, brain: Path) -> Path:
    path = Path(value).expanduser()
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, action.WORK / path, brain / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ActionError("not_found", f"No file {value}")


def brain_of(args: argparse.Namespace) -> Path:
    return (args.brain[0] if args.brain else action.BRAIN).expanduser().resolve()


def run_check(args: argparse.Namespace) -> tuple[list[Report], int]:
    brain = brain_of(args)
    reports = []
    for value in args.files:
        file = resolve_file(value, brain)
        text = file.read_text(encoding="utf-8")
        reports.append(check_text(text, display(file), file.parent, file.name))
    return reports, sum(r.errors for r in reports)


def print_reports(reports: list[Report], as_json: bool) -> None:
    if as_json:
        payload = {
            "files": [
                {
                    "path": r.path,
                    "findings": [{"line": f.line, "severity": f.severity, "message": f.message} for f in r.findings],
                    "words": r.words,
                    "cap": r.cap,
                    "duration_minutes": r.duration,
                    "errors": r.errors,
                    "warnings": r.warnings,
                }
                for r in reports
            ],
            "errors": sum(r.errors for r in reports),
            "warnings": sum(r.warnings for r in reports),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for r in reports:
        for f in r.findings:
            print(f"{r.path}:{f.line}  {f.severity}  {f.message}")
        if r.words is None:
            print(f"{r.path}  info  not checked")
            continue
        used = "duration unknown" if r.duration is None else f"duration {format_minutes(r.duration)} min"
        print(f"{r.path}  info  body {r.words} words / cap {r.cap} ({used}); {r.errors} errors, {r.warnings} warnings")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check meeting minutes and keep the monthly source index.")
    sub = parser.add_subparsers(dest="command", required=True)
    brain_help = "brain to use (default: BRAIN_DIR, else the default brain of Work)"

    p = sub.add_parser("check", help="check minutes against the rules of cr-reunion")
    p.add_argument("files", nargs="+", metavar="FILE", help="minutes to check")
    p.add_argument("--brain", action="append", type=Path, metavar="PATH", help=brain_help)
    p.add_argument("--json", action="store_true", help="print JSON instead of text lines")

    index = sub.add_parser("index", help="maintain sources/YYYY-MM/index.md").add_subparsers(dest="index_command", required=True)
    p = index.add_parser("add", help="add the line of a source to the index of its folder")
    p.add_argument("file", metavar="FILE", help="source to list")
    p.add_argument("--subject", default="", help=f"subject of the line ({SUBJECT_WORDS} words at most)")
    p.add_argument("--brain", action="append", type=Path, metavar="PATH", help=brain_help)
    p.add_argument("--dry-run", action="store_true", help="print the line and its position without writing")
    p.add_argument("--json", action="store_true", help="accepted for symmetry: the output is always JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "check":
            reports, errors = run_check(args)
            print_reports(reports, args.json)
            return 1 if errors else 0
        result = index_add(resolve_file(args.file, brain_of(args)), args.subject, args.dry_run)
    except ActionError as error:
        print(json.dumps({"error": error.message, "kind": error.kind}, ensure_ascii=False))
        return EXIT[error.kind]
    except (OSError, UnicodeDecodeError) as error:
        print(json.dumps({"error": str(error), "kind": "conflict"}, ensure_ascii=False))
        return EXIT["conflict"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    action.load_work_config().utf8_stdio()
    sys.exit(main())
