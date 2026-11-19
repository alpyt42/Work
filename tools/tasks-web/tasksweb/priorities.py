"""Priorities: read the ranked list a brain's priorities skill writes for the Priorities view."""

from __future__ import annotations

import hashlib
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .markdown import MARKDOWN, split_front_matter
from .docs import DOC_SIZE_LIMIT

PRIORITY_SECTIONS = {"warnings": "warnings", "now": "now", "prepare": "prepare", "conflicts": "conflicts", "new requests": "new-requests",
                     "follow-ups": "follow-ups", "to chase": "to-chase", "to close": "to-close", "lingering": "lingering", "admin": "admin"}


def priorities_sections(text: str) -> tuple[str | None, list[dict]]:
    """The `# ` title and the `## ` sections of a priorities file, each rendered with the safe Markdown renderer."""
    lines = text.splitlines()
    tokens = MARKDOWN.parse(text, {})
    headings = [(token.map[0], token.map[1], tokens[index + 1].content.strip(), token.tag)
                for index, token in enumerate(tokens) if token.type == "heading_open"]
    title = next((heading[2] for heading in headings if heading[3] == "h1"), None)
    starts = [heading for heading in headings if heading[3] == "h2"]
    sections = []
    for position, (_, end, heading, _tag) in enumerate(starts):
        stop = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[end:stop])
        count = sum(1 for token in MARKDOWN.parse(body, {}) if token.type == "list_item_open" and token.level == 1)
        env = {"id": "priorities", "ids": set(), "line_offset": 0}
        sections.append({"key": PRIORITY_SECTIONS.get(heading.lower(), "other"), "title": heading, "count": count,
                         "html": MARKDOWN.render(body, env)})
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
