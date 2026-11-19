"""Settings: the Work configuration of this computer, in plain words, editable.

`GET /api/settings` answers with what a business user can read and change; `POST /api/settings` saves one setting
through tools/machine/setup.py (`apply`, which validates and writes it where it belongs). Technical settings (the
Git remote and e-mail patterns of a brain) and the checks only an owner or an agent can do are never editable here:
the page only says that the agent takes care of them. Every user-facing string is plain language: no command, no
file name, no JSON key. Only names, values and states are returned: never the content of `.env`,
`.data/client-repos.json`, keys or SSH and home configuration, which no section reads. A section that fails
reports an `error` and leaves the others intact.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from http import HTTPStatus
from pathlib import Path

from .common import TOOLS_ROOT, TaskError, preflight_push
from .markdown import split_front_matter
from .brains import brain_label

_setup_spec = importlib.util.spec_from_file_location("work_setup", TOOLS_ROOT / "tools/machine/setup.py")
assert _setup_spec and _setup_spec.loader
setup_tool = importlib.util.module_from_spec(_setup_spec)
sys.modules["work_setup"] = setup_tool  # dataclasses look their module up here
_setup_spec.loader.exec_module(setup_tool)
SETTINGS_LOCK = threading.Lock()
SETTINGS_TEXT_LIMIT = 600
SETTINGS_VALUE_LIMIT = 600
SETTINGS_BRAIN_FIELDS = ("owner", "description", "scope")  # the fields of a brain a business user may change
SETTINGS_KEYS = ("defaultBrain", "artifactsDir", "transcripts_dir", "brains")
SETTINGS_TECHNICAL_RE = re.compile(r"uv run|\.py\b|\.sh\b|\.json\b|\.env\b|setup\.py|work\.py|update\.sh|[`<>]|://|\bgit\b", re.IGNORECASE)
SKILL_CODE_ASIDE_RE = re.compile(r"\s*(?:—[^—]*`[^—]*—|\([^()]*`[^()]*\))")  # an aside between dashes or brackets that holds code
SKILL_COMMAND_RE = re.compile(r"uv run|\.py\b|\.sh\b|\.json\b|\.env\b|[<>]|://", re.IGNORECASE)  # a skill summary that still holds a command is not shown
SETTINGS_CHECK_TITLES = {
    "command.git": "A program that keeps the history of your notes is missing on this computer.",
    "command.uv": "A program that runs the workspace tools is missing on this computer.",
    "command.npx": "A program needed to install some skills is missing on this computer.",
    "install": "The workspace is not fully set up yet.",
    "bootstrap": "The workspace setup is incomplete on this computer.",
    "git-identity": "The name and e-mail used to sign your saved work need attention on this computer.",
    "artifacts-link": "The deliverables folder is not connected to the workspace yet.",
    "tools-env": "Some access details needed by your skills are missing on this computer.",
    "expected-brains": "Some brains that every computer must have are not on this computer yet.",
    "transcripts-folder": "Your meeting transcripts folder is not on this computer.",
    "obsidian": "Your notes app (Obsidian) is not set up on this computer.",
}
SETTINGS_CHECK_FALLBACK = "Something needs attention on this computer."
SETTINGS_DAMAGED = "A settings file on this computer is damaged: ask your agent to look at it."


def settings_text(value: object) -> str:
    """A configured string as shown: one line, credentials of a URL hidden, bounded."""
    text = " ".join(str(value).split())
    return "".join(char for char in preflight_push.redact(text) if char.isprintable())[:SETTINGS_TEXT_LIMIT]


def settings_config_module(work: Path):
    """A private copy of work_config.py pointed at `work` (its functions read module-level paths)."""
    spec = importlib.util.spec_from_file_location("work_config_view", TOOLS_ROOT / "tools/machine/work_config.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.EXAMPLE, module.LOCAL, module.LOCK, module.STATE = (
        work, work / "work-config.example.json", work / "work-config.local.json", work / "skills-lock.json", work / ".work-state.json")
    return module


def settings_json_object(path: Path) -> tuple[dict | None, bool]:
    """(object, False) of a JSON file; (None, False) when absent; (None, True) when unreadable or not an object."""
    if not path.is_file():
        return None, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, True
    return (data, False) if isinstance(data, dict) else (None, True)


def settings_found_brains(wc, work: Path) -> list[Path]:
    try:
        return wc.discover_brains(work)
    except (wc.ConfigError, OSError):
        try:
            return wc.find_brains(work)
        except OSError:
            return []


def settings_key_editable(key: str, names: list[str]) -> bool:
    """A key the page may write: four workspace settings, and owner, description and kind of a brain of this Work."""
    name, dot, field = key.partition(".")
    return key in SETTINGS_KEYS or bool(dot and name in names and field in SETTINGS_BRAIN_FIELDS)


def settings_check_title(item) -> str:
    title = SETTINGS_CHECK_TITLES.get(item.key)
    if title:
        return title
    why = settings_text(item.why).rstrip(".")
    return f"{why[:1].upper()}{why[1:]} needs attention." if why and not SETTINGS_TECHNICAL_RE.search(why) else SETTINGS_CHECK_FALLBACK


def settings_brain_options(wc, brains: list[Path], extra: list[str] = ()) -> list[dict]:
    options = [{"name": brain.name, "label": brain_label(brain.name), "present": True} for brain in brains]
    options += [{"name": name, "label": brain_label(name), "present": False} for name in extra if name not in {brain.name for brain in brains}]
    return options


def settings_todo_item(item, options: list[dict]) -> dict:
    """One missing, editable setting as a plain question with the value to prefill."""
    key = item.key
    entry: dict = {"key": key, "input": "text", "value": item.default or "", "has_default": item.default is not None, "placeholder": "", "options": []}
    brain, _, field = key.partition(".")
    label = brain_label(brain) if field else ""
    if key == "defaultBrain":
        entry.update(label="Which brain should the app open by default?", input="brain", value=item.suggestion or (options[0]["name"] if options else ""), options=options)
    elif key == "artifactsDir":
        entry.update(label="Where should your deliverables and received files be kept? Keep the default to store them inside the workspace, or enter the full path of a synced folder.")
    elif key == "transcripts_dir":
        entry.update(label="Which folder holds your meeting transcripts? Give its place inside your home folder.")
    elif key == "brains":
        names = [part.strip() for part in (item.default or "").split(",") if part.strip()]
        entry.update(label="Which brains must every computer have?", input="brains", value=names, options=options)
    elif field == "owner":
        entry.update(label=f"Whose name should the actions of {label} carry?", placeholder="First and last name")
    elif field == "scope":
        entry.update(label=f"What kind of brain is {label}?", input="scope", value=item.default or item.suggestion or "")
    else:
        entry.update(label=f"In one sentence, what does {label} hold, and what must it never hold?", input="textarea", placeholder="What it holds, and what it must never hold")
    if item.detail and "not on this machine" in item.detail:
        entry["note"] = "The folder chosen before is not on this computer."
    return entry


def settings_setup(work: Path, wc, brains: list[Path]) -> dict:
    names = [brain.name for brain in brains]
    options = settings_brain_options(wc, brains)
    todo, agent, technical = [], [], False
    for item in setup_tool.collect(work):
        if item.kind == "setting" and item.state == "missing":
            if settings_key_editable(item.key, names):
                todo.append(settings_todo_item(item, options))
            else:
                technical = True
        elif item.kind == "check" and item.state == "owner-action":
            agent.append({"key": item.key, "title": settings_check_title(item)})
    return {"todo": todo, "technical_missing": technical, "agent": agent}


def settings_workspace(work: Path, wc, brains: list[Path]) -> dict:
    local, _ = settings_json_object(wc.LOCAL)
    try:
        default = wc.default_brain(work)
    except wc.ConfigError:
        default = None
    options = settings_brain_options(wc, brains)
    result: dict = {"default_brain": {"key": "defaultBrain", "value": default.name if default else "", "label": brain_label(default.name) if default else "",
                                      "options": options, "problem": "" if default else "No default brain is chosen yet."}}
    configured = isinstance(local, dict) and isinstance(local.get("artifactsDir"), str)
    folder = wc.artifacts_dir(work)
    inside = folder.resolve().is_relative_to(work.resolve())
    link = work / wc.ARTIFACTS
    warnings = []
    if not folder.is_dir():
        warnings.append("This folder is not on this computer.")
    elif not inside and not (link.is_symlink() and link.resolve() == folder.resolve()):
        warnings.append("The folder is not connected to the workspace yet: ask your agent to take care of it.")
    result["artifacts"] = {"key": "artifactsDir", "value": local["artifactsDir"].strip() if configured else "", "status": "Inside Work" if inside else "Synced folder",
                           "warnings": warnings}
    paths, _ = settings_json_object(default / ".data/local-paths.json") if default else (None, False)
    transcripts = paths.get("transcripts_dir") if paths else None
    value = transcripts.strip() if isinstance(transcripts, str) else ""
    warnings = []
    if value and not Path(value).is_absolute() and ".." not in Path(value).parts and not (Path.home() / value).is_dir():
        warnings.append("This folder is not on this computer yet.")
    result["transcripts"] = {"key": "transcripts_dir", "value": value, "note": "Relative to your home folder.", "warnings": warnings}
    expected = paths.get("brains") if paths else None
    wanted = [name for name in expected if isinstance(name, str)] if isinstance(expected, list) else []
    present = {brain.name for brain in brains}
    result["needed_brains"] = {"key": "brains", "value": wanted, "options": settings_brain_options(wc, brains, wanted),
                               "warnings": [f"{brain_label(name)} is not on this computer yet: ask your agent to fetch it." for name in wanted if name not in present]}
    return result


def settings_scope_kind(scope: str) -> str:
    return scope if scope in ("personal", "employer", "client") else "other" if scope else ""


def settings_brains(wc, brains: list[Path], default: str) -> list[dict]:
    result = []
    for brain in brains:
        boundary, boundary_bad = settings_json_object(brain / ".data/brain.json")
        doctor, doctor_bad = settings_json_object(brain / ".data/doctor.json")
        scope = settings_text(boundary["scope"]) if boundary and isinstance(boundary.get("scope"), str) else ""
        result.append({
            "name": brain.name, "label": brain_label(brain.name), "default": brain.name == default,
            "owner": settings_text(doctor["owner"]) if doctor and isinstance(doctor.get("owner"), str) else "",
            "description": settings_text(boundary["description"]) if boundary and isinstance(boundary.get("description"), str) else "",
            "scope": scope, "kind": settings_scope_kind(scope),
            "problem": "The details of this brain cannot be read: ask your agent to look at them." if boundary_bad or doctor_bad else "",
        })
    return result


def settings_skill_summary(path: Path) -> str:
    """The first sentence of the `description` in the front matter of a SKILL.md; "" when absent or too technical to show."""
    try:
        text = path.read_text(encoding="utf-8")[:20000]
    except (OSError, UnicodeDecodeError):
        return ""
    value = next((value for key, value in split_front_matter(text)[0] if key == "description"), "")
    value = re.sub(r"^[>|][+-]?\s*", "", value).strip().strip("\"'").strip()
    # An aside that names files or code ("— the lines of `inbox/inbox.md` —") goes; other code spans keep their words.
    value = SKILL_CODE_ASIDE_RE.sub("", value).replace("`", "")
    sentence = settings_text(re.split(r"(?<=[.!?])\s", value, maxsplit=1)[0])
    if len(sentence) > 200:
        sentence = sentence[:199].rstrip() + "…"
    return "" if SKILL_COMMAND_RE.search(sentence) else sentence


def settings_skills(work: Path, wc, brains: list[Path]) -> dict:
    config = wc.resolve()
    disabled = set(config["disabled"])
    groups = []
    for brain in brains:
        skills = [{"name": name, "summary": settings_skill_summary(skill["path"] / "SKILL.md")}
                  for name, skill in sorted(config["own"].items()) if skill["brain"] == brain.name and name not in disabled]
        if skills:
            groups.append({"title": f"From {brain_label(brain.name)}", "skills": skills})
    elsewhere = []
    for name in sorted(config["thirdParty"]):
        if name not in disabled:
            installed = next((work / folder / name / "SKILL.md" for folder in (".claude/skills", ".agents/skills") if (work / folder / name / "SKILL.md").is_file()), None)
            elsewhere.append({"name": name, "summary": settings_skill_summary(installed) if installed else ""})
    if elsewhere:
        groups.append({"title": "Installed from elsewhere", "skills": elsewhere})
    return {"groups": groups, "turned_off": sorted(disabled), "needs_refresh": wc.stamp_state(config) != "current"}


def settings_snapshot(work: Path) -> dict:
    """The Settings view: what is left to complete, what the agent must do, the workspace, the brains and the skills; an `error` per failed section."""
    result: dict = {}
    with SETTINGS_LOCK:
        wc = settings_config_module(work)
        setup_tool.work_config = wc  # the checklist reads the same Work as the sections below
        brains = settings_found_brains(wc, work)
        try:
            default = wc.default_brain(work)
        except (wc.ConfigError, OSError):
            default = None
        default_name = default.name if default else ""
        sections = {
            "setup": lambda: settings_setup(work, wc, brains),
            "workspace": lambda: settings_workspace(work, wc, brains),
            "brains": lambda: {"brains": settings_brains(wc, brains, default_name)},
            "skills": lambda: settings_skills(work, wc, brains),
        }
        for name, build in sections.items():
            try:
                result[name] = build()
            except (wc.ConfigError, setup_tool.SetupError):
                result[name] = {"error": SETTINGS_DAMAGED}
            except (OSError, ValueError, KeyError, TypeError):
                result[name] = {"error": "This part of the settings cannot be read right now."}
    return result


def settings_plain_error(key: str, problem: str) -> str:
    """A refusal of tools/machine/setup.py in plain words: never a command, a file name or a technical term."""
    text = problem.lower()
    field = key.partition(".")[2] if "." in key else key
    if "cannot read" in text or "fix it by hand" in text or "would be invalid" in text or "json object" in text:
        return SETTINGS_DAMAGED
    if "answer defaultbrain first" in text or "no default brain" in text:
        return "Choose the default brain first."
    if field == "defaultBrain":
        return "Choose one of the brains of this workspace."
    if field == "artifactsDir":
        if "does not exist" in text:
            return "That folder does not exist yet: create it or sync it on this computer first, then try again."
        if "not a folder" in text:
            return "That is not a folder."
        return "Enter a folder inside the workspace, or the full path of a synced folder."
    if field == "transcripts_dir":
        if "outside the workspace" in text:
            return "Choose a folder outside the workspace."
        return "Choose a folder inside your home folder."
    if field == "brains":
        if "must include the default" in text:
            return "The list must include the default brain."
        return "Choose among the brains of this workspace."
    if field == "owner":
        return "Enter a name, in 120 characters at most." if "empty" not in text else "Enter a name."
    if field == "description":
        return "Describe in one sentence what it holds." if "empty" in text else "Keep it short: 500 characters at most."
    if field == "scope":
        return "Use a short word, such as personal, employer or client."
    return "This value cannot be saved. Check it and try again."


def settings_plain_notes(lines: list[str]) -> list[str]:
    notes = []
    for line in lines:
        if not line.startswith("note: "):
            continue
        note = line[6:]
        if note.startswith("created "):
            notes.append("The folder was created.")
        elif "does not link" in note:
            notes.append("Your agent still has to connect this folder to the workspace: ask it to take care of it.")
        elif "not at the Work root" in note:
            notes.append("Some of these brains are not on this computer yet: ask your agent to fetch them.")
        elif "not on this machine" in note:
            notes.append("This folder is not on this computer yet.")
    return notes


def settings_apply(work: Path, key: str, value: str | None) -> str:
    """Save one setting (None: its default) and return the message to show; TaskError 400 with a plain message when it is refused."""
    with SETTINGS_LOCK:
        wc = settings_config_module(work)
        setup_tool.work_config = wc
        names = [brain.name for brain in settings_found_brains(wc, work)]
        if not settings_key_editable(key, names):
            raise TaskError(HTTPStatus.BAD_REQUEST, "This setting cannot be changed here.")
        try:
            lines = setup_tool.apply(work, key, value)
        except setup_tool.SetupError as problem:
            raise TaskError(HTTPStatus.BAD_REQUEST, settings_plain_error(key, str(problem))) from None
        except (wc.ConfigError, OSError):
            raise TaskError(HTTPStatus.BAD_REQUEST, SETTINGS_DAMAGED) from None
    if lines and "already set" in lines[0]:
        return "Already set: nothing was changed."
    parts = ["Reset to the default." if value is None else "Saved.", *settings_plain_notes(lines)]
    if key == "defaultBrain":
        parts.append("The new default brain applies the next time the app starts.")
    return " ".join(parts)
