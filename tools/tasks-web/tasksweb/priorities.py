"""Priorities: read the ranked list a brain's priorities skill writes for the Priorities view."""

from __future__ import annotations

import hashlib
import re
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from markdown_it.common.utils import escapeHtml

from .markdown import build_markdown, split_front_matter
from .docs import DOC_SIZE_LIMIT

PRIORITY_SECTIONS = {"warnings": "warnings", "now": "now", "prepare": "prepare", "conflicts": "conflicts", "new requests": "new-requests",
                     "follow-ups": "follow-ups", "to chase": "to-chase", "to close": "to-close", "lingering": "lingering", "admin": "admin"}

DRAFT_HEADER_RE = re.compile(r"^([A-Za-z][\w-]*)[ \t]*:[ \t]*(.*?)[ \t]*$")
DRAFT_ROWS = (("to", "To"), ("cc", "Cc"), ("subject", "Subject"), ("thread", "Thread"), ("send", "Send"))
DRAFT_CHANNELS = {"mail": "Mail", "teams": "Teams"}
DRAFT_ADDRESS_RE = re.compile(r"\s*<[^>]*>")


def parse_draft(text: str) -> tuple[list[tuple[str, str]], str]:
    """Split a `draft` block into its `key: value` headers (up to the first blank line) and its body, kept as written."""
    lines = text.rstrip("\n").split("\n")
    known = {"channel", *(key for key, _ in DRAFT_ROWS)}
    first = DRAFT_HEADER_RE.match(lines[0]) if lines else None
    if not first or first.group(1).lower() not in known:
        return [], "\n".join(lines)
    headers: list[tuple[str, str]] = []
    position = 0
    while position < len(lines) and lines[position].strip():
        match = DRAFT_HEADER_RE.match(lines[position])
        if not match:
            return headers, "\n".join(lines[position:])
        headers.append((match.group(1), match.group(2)))
        position += 1
    return headers, "\n".join(lines[position:]).lstrip("\n")


def render_draft(text: str) -> str:
    """A draft as a closed `<details>`: summary (channel, recipients, subject or thread), header rows, body as plain text."""
    headers, body = parse_draft(text)
    values: dict[str, str] = {}
    extra: list[tuple[str, str]] = []
    for key, value in headers:
        if key.lower() in {"channel", *(name for name, _ in DRAFT_ROWS)}:
            values[key.lower()] = value
        else:
            extra.append((key, value))
    channel = values.get("channel", "")
    label = DRAFT_CHANNELS.get(channel.lower()) or channel or "Draft"
    recipients = DRAFT_ADDRESS_RE.sub("", values.get("to", "")).strip()
    subject = values.get("subject") or values.get("thread", "")
    parts = [f'<span class="prio-draft-channel">{escapeHtml(label)}</span>']
    if recipients:
        parts.append(f'<span class="prio-draft-to">{escapeHtml(recipients)}</span>')
    if subject:
        parts.append(f'<span class="prio-draft-subject">{escapeHtml(subject)}</span>')
    rows = [(title, values[key]) for key, title in DRAFT_ROWS if key in values] + extra
    meta = "".join(f"<div><dt>{escapeHtml(title)}</dt><dd>{escapeHtml(value)}</dd></div>" for title, value in rows)
    meta = f'<dl class="prio-draft-meta">{meta}</dl>\n' if meta else ""
    return (f'<details class="prio-draft">\n<summary>{" · ".join(parts)}</summary>\n{meta}'
            f'<div class="prio-draft-body">{escapeHtml(body)}</div>\n</details>\n')


def build_priorities_markdown():
    """The document renderer plus the `draft` fence; the renderer of the documents (`MARKDOWN`) is left alone."""
    markdown = build_markdown()
    fence = markdown.renderer.rules["fence"]

    def render_fence(tokens, idx, options, env):
        token = tokens[idx]
        if token.info.strip().split(" ")[0] == "draft":
            return render_draft(token.content)
        return fence(tokens, idx, options, env)

    markdown.renderer.rules["fence"] = render_fence
    return markdown


PRIORITIES_MARKDOWN = build_priorities_markdown()


def priorities_sections(text: str) -> tuple[str | None, list[dict]]:
    """The `# ` title and the `## ` sections of a priorities file, each rendered with the safe Markdown renderer."""
    lines = text.splitlines()
    tokens = PRIORITIES_MARKDOWN.parse(text, {})
    headings = [(token.map[0], token.map[1], tokens[index + 1].content.strip(), token.tag)
                for index, token in enumerate(tokens) if token.type == "heading_open"]
    title = next((heading[2] for heading in headings if heading[3] == "h1"), None)
    starts = [heading for heading in headings if heading[3] == "h2"]
    sections = []
    for position, (_, end, heading, _tag) in enumerate(starts):
        stop = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[end:stop])
        count = sum(1 for token in PRIORITIES_MARKDOWN.parse(body, {}) if token.type == "list_item_open" and token.level == 1)
        env = {"id": "priorities", "ids": set(), "line_offset": 0}
        sections.append({"key": PRIORITY_SECTIONS.get(heading.lower(), "other"), "title": heading, "count": count,
                         "html": PRIORITIES_MARKDOWN.render(body, env)})
    return title, sections


def priorities_stale(generated: str | None, today: str) -> bool:
    """True when `generated` is missing, unparsable or dated (in its own offset) before `today`."""
    try:
        return datetime.fromisoformat(generated or "").date().isoformat() < today
    except ValueError:
        return True


def read_priorities(work: Path, name: str) -> dict:
    """The priorities file of a brain (`priorities/<name>.md` under Work), parsed for the Priorities view."""
    missing = {"brain": name, "exists": False, "path": f"priorities/{name}.md"}
    folder = work / "priorities"
    path = folder / f"{name}.md"
    try:
        if not stat.S_ISREG(path.lstat().st_mode) or path.resolve().parent != folder.resolve():
            return missing
        with open(path, "rb") as handle:
            data = handle.read(DOC_SIZE_LIMIT + 1)
    except OSError:
        return missing
    if len(data) > DOC_SIZE_LIMIT:
        return missing
    properties, body = split_front_matter(data.decode("utf-8", "replace").lstrip("\ufeff"))
    meta = {key: value.strip("\"'") for key, value in properties}
    title, sections = priorities_sections(body)
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    generated = meta.get("generated") or None
    return {**missing, "exists": True, "title": title, "generated": generated, "horizon": meta.get("horizon") or None,
            "next_meeting": meta.get("next_meeting") or None, "stale": priorities_stale(generated, today), "today": today,
            "version": hashlib.sha256(data).hexdigest()[:16], "sections": sections}
