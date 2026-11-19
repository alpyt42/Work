"""The brains of Work: discovery, the default brain, labels, client names and trust boundaries."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import WORK, work_config
from .markdown import FENCE_RE, HEADING_RE, split_front_matter


def discover_brains(work: Path) -> list[Path]:
    """Brains at the Work root, the default brain first then by name.

    The rule is the one of tools/machine/work_config.py (a folder named `brain` or `brain-<name>` that holds an
    AGENTS.md and a .data/ folder, a test compares the tools). A `defaultBrain` setting that cannot be applied
    leaves them by name; tools/machine/doctor.py reports the setting.
    """
    try:
        try:
            return work_config.discover_brains(work)
        except work_config.ConfigError:
            return work_config.find_brains(work)
    except OSError:
        return []


def default_brain_dir() -> Path:
    """The default brain of Work (the `--brain` default); `Work/brain` when there is none. ConfigError if the setting is invalid."""
    try:
        return work_config.default_brain(WORK) or WORK / "brain"
    except OSError:
        return WORK / "brain"


def brain_option(value: Path, work: Path) -> Path:
    """The folder `--brain` names; ValueError when it is not a brain.

    A relative value is read from the Work root the server serves (`work`: WORK_DIR, else this checkout), never from the
    directory the command is run in: with WORK_DIR set, `--brain brain-acme` would otherwise serve the brain-acme of the
    current directory, a brain of another Work, without a word. A brain is a folder that holds an AGENTS.md and a .data/
    folder (the rule of tools/machine/work_config.py); its name is free, since the default brain may live outside Work.
    """
    path = (value if value.is_absolute() else work / value).resolve()
    if not (path.is_dir() and (path / "AGENTS.md").is_file() and (path / ".data").is_dir()):
        where = "" if value.is_absolute() else f"; a relative --brain is read from the Work root, {work}"
        raise ValueError(f"--brain {value}: {path} is not a brain (a folder holding AGENTS.md and .data/){where}")
    return path


def brain_label(name: str) -> str:
    """Short name shown in the page: `brain-initech` -> `Initech`, `brain-acme-corp` -> `Acme-corp`, `brain` -> `Brain`.

    The folder name stays the technical value (`brain=`, local storage, API); only the label is displayed.
    A name outside the `brain` / `brain-<name>` convention (a default brain given with --brain) just gets an initial capital.
    """
    short = name.removeprefix("brain-") or name
    return short[:1].upper() + short[1:]


CLIENT_HEADING_PREFIX_RE = re.compile(r"^client\s*:\s*", re.IGNORECASE)
CLIENT_PAGE_READ = 8192


def client_display_name(folder: Path) -> str:
    """How the page names a client: the first level-1 heading of `<client>/<client>.md` without its `Client:` prefix
    (`# Client: Acme Labs` -> `Acme Labs`, a heading without the prefix as it is), else the folder name with
    each word capitalised (`globex-industries` -> `Globex Industries`). Only displayed: the folder name stays the value
    the API addresses (register paths, labels)."""
    page = folder / f"{folder.name}.md"
    try:
        if page.is_file() and not page.is_symlink():
            with open(page, "rb") as handle:
                text = handle.read(CLIENT_PAGE_READ).decode("utf-8", "replace").lstrip("﻿")
            fenced = False
            for line in split_front_matter(text)[1].splitlines():
                if FENCE_RE.match(line):
                    fenced = not fenced
                    continue
                heading = None if fenced else HEADING_RE.match(line)
                if heading and len(heading.group(1)) == 1:
                    name = " ".join(CLIENT_HEADING_PREFIX_RE.sub("", heading.group(2).strip()).split())
                    if name:
                        return name[:120]
                    break
    except OSError:
        pass
    return " ".join(word[:1].upper() + word[1:] for word in re.split(r"[-_\s]+", folder.name) if word) or folder.name


def client_names(brain: Path) -> dict[str, str]:
    """Folder name -> display name of every client of the brain, the archived ones too (a live client wins a shared name)."""
    clients = brain / "projects/clients"
    names: dict[str, str] = {}
    for shelf in (clients / "archive", clients):
        try:
            folders = sorted(shelf.iterdir()) if shelf.is_dir() and not shelf.is_symlink() else []
        except OSError:
            folders = []
        for folder in folders:
            if folder.is_dir() and not folder.is_symlink() and not folder.name.startswith(".") and folder.name != "archive":
                names[folder.name] = client_display_name(folder)
    return names


def brain_boundary(brain: Path) -> dict[str, str]:
    """`scope` and `description` of <brain>/.data/brain.json; empty strings when the file is missing or unreadable."""
    values = {"scope": "", "description": ""}
    try:
        declared = json.loads((brain / ".data/brain.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if isinstance(declared, dict):
        for key in values:
            if isinstance(declared.get(key), str):
                values[key] = " ".join(declared[key].split())
    return values
