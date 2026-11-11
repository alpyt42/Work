#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List, check, report on, or clone repositories from the private brain catalog.

Run from the Work root: the default brain (see tools/machine/work_config.py) is found at the Work root, two levels
above this script. Set WORK_DIR or BRAIN_DIR only to use another location. The catalog contains URLs only;
credentials and key paths stay local.

Catalog `.data/client-repos.json`: {"schema_version": 1 or 2, "repositories": [entry, ...]}. An entry is
{"path": "repos/<group>/<name>", "url": "<ssh url>"}; folder names start with a letter or digit and contain letters,
digits, ".", "_" or "-". Version 2 adds an optional "project" (a brain project as `brain-state.py brief` accepts it:
"acme/demo" or "notes": plain text, one "/" at most, no ".."). Version 1 entries carry no project.

Commands (all local, no network except `clone`):
  list [selector] [--project P] [--present | --missing] [--json]   without these flags: "path  url" lines;
      with one of them: "present|missing  path  project-or--" lines; --json adds url and present.
      --project matches the entry's project exactly (entries without project never match).
  check [selector]    compares each clone's origin with the catalog and shows the author and key it gets.
  status [selector] [--project P] [--json]   branch, changes, ahead/behind of the local upstream ref and last commit
      date of each present repository, then Git roots under repos/ that no entry names (skipped with --project).
  clone <selector>    clones the repositories of a group or one path.

Author and SSH key come from the user's ~/.gitconfig rules (by folder and by
remote URL, see tools/machine/gitconfig.example); `check` shows what each clone gets.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path


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
CATALOG = BRAIN / ".data/client-repos.json"
PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SSH_URL = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+\.git$")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def valid_part(part: str) -> bool:
    return bool(PART.fullmatch(part)) and ".." not in part


def catalog() -> list[dict[str, str]]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version not in (1, 2) or not isinstance(data.get("repositories"), list):
        raise ValueError("unsupported client repository catalog")
    allowed = {"path", "url"} if version == 1 else {"path", "url", "project"}
    repositories: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data["repositories"]:
        if not isinstance(item, dict) or not {"path", "url"} <= set(item) <= allowed:
            raise ValueError("catalog entries must contain only path and url" if version == 1
                             else "catalog entries must contain only path, url and optional project")
        path, url = item["path"], item["url"]
        if not isinstance(path, str) or not isinstance(url, str):
            raise ValueError("catalog path and url must be strings")
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "repos" or not all(valid_part(p) for p in parts[1:]):
            raise ValueError(f"unsafe repository path: {path}")
        if path in seen:
            raise ValueError(f"duplicate repository path: {path}")
        if not SSH_URL.fullmatch(url) or ".." in url:
            raise ValueError(f"unsafe or non-SSH URL for {path}")
        if "project" in item:
            project = item["project"]
            if not isinstance(project, str) or not 1 <= len(project.split("/")) <= 2 or not all(
                valid_part(p) for p in project.split("/")
            ):
                raise ValueError(f"unsafe project for {path}")
        seen.add(path)
        repositories.append(item)
    return repositories


def selected(items: list[dict[str, str]], selector: str | None) -> list[dict[str, str]]:
    if selector is None:
        return items
    matches = [item for item in items if item["path"] == selector or item["path"].split("/")[1] == selector]
    if not matches:
        raise ValueError(f"unknown client or repository: {selector}")
    return matches


def destination(relative: str) -> Path:
    repos = WORK / "repos"
    if repos.is_symlink() or not repos.resolve().is_relative_to(WORK):
        raise ValueError("repos/ must be inside the Work checkout")
    target = WORK / relative
    if target.is_symlink() or not target.parent.resolve().is_relative_to(repos.resolve()):
        raise ValueError(f"repository destination escapes Work: {relative}")
    return target


def existing_remote(target: Path) -> str:
    if not (target / ".git").exists():
        raise ValueError(f"destination exists but is not a Git clone: {target}")
    if Path(git(target, "rev-parse", "--show-toplevel")).resolve() != target.resolve():
        raise ValueError(f"destination is not its own Git repository: {target}")
    return git(target, "remote", "get-url", "origin")


def effective(repo: Path, key: str) -> tuple[str, str]:
    """Effective value of a Git setting in repo and the file it comes from."""
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--show-origin", "--get", key], capture_output=True, text=True
    )
    if result.returncode or "\t" not in result.stdout:
        return "", ""
    origin, value = result.stdout.rstrip("\n").split("\t", 1)
    origin = origin.removeprefix("file:")
    local = bool(origin) and (repo / origin).resolve() == (repo / ".git/config").resolve()
    return value, "local clone" if local else Path(origin).name


def identity_summary(repo: Path) -> tuple[str, bool]:
    """Human-readable author and key applied in repo, and whether an author exists."""
    email, email_origin = effective(repo, "user.email")
    command, command_origin = effective(repo, "core.sshCommand")
    key = re.search(r"-i\s+(\S+)", command)
    key_text = f"{key.group(1)} ({command_origin})" if key else "chosen by ~/.ssh/config"
    author = f"{email} ({email_origin})" if email else "none"
    return f"author={author} · key={key_text}", bool(email)


def check(items: list[dict[str, str]]) -> int:
    mismatches = 0
    for item in items:
        target = destination(item["path"])
        if not target.exists():
            print(f"MISSING   {item['path']}")
            continue
        try:
            actual = existing_remote(target)
        except (ValueError, subprocess.CalledProcessError) as exc:
            print(f"ERROR     {item['path']}: {exc}")
            mismatches += 1
            continue
        if actual != item["url"]:
            visible = actual if SSH_URL.fullmatch(actual) and ".." not in actual else "<non-SSH URL hidden>"
            print(f"DIFFERENT {item['path']}: origin={visible}; catalog={item['url']}")
            mismatches += 1
            continue
        summary, has_author = identity_summary(target)
        if has_author:
            print(f"OK        {item['path']}  {summary}")
        else:
            print(f"IDENTITY  {item['path']}  {summary} : no user.email (~/.gitconfig rule missing or incomplete)")
            mismatches += 1
    return 1 if mismatches else 0


def ssh_command(identity_arg: str) -> str:
    identity = Path(identity_arg)
    if not identity.is_absolute() or not identity.is_file():
        raise ValueError("--identity must name an existing absolute key path")
    identity = identity.resolve()
    if identity.is_relative_to(WORK):
        raise ValueError("SSH keys must stay outside Work")
    if stat.S_IMODE(identity.stat().st_mode) & 0o077:
        raise ValueError("SSH key permissions must be owner-only")
    return shlex.join([
        "ssh", "-F", "/dev/null", "-i", str(identity),
        "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
    ])


def home_rules_cover(target: Path, url: str) -> str:
    """Author email the home rules would give a clone of url at target ("" if none).

    Evaluated in a throwaway repository at the destination so that both
    `gitdir:` and `hasconfig:remote.*.url:` conditions apply; target is left empty.
    """
    target.mkdir(parents=True)
    try:
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "add", "origin", url], check=True)
        return effective(target, "user.email")[0]
    finally:
        shutil.rmtree(target / ".git", ignore_errors=True)


def clone(items: list[dict[str, str]], identity: str | None, author_name: str | None, author_email: str | None) -> int:
    override = identity or author_name or author_email
    environment = os.environ.copy()
    if override:
        if not (identity and author_name and author_name.strip() and author_email and "@" in author_email):
            raise ValueError("an override needs --identity, --author-name and --author-email together")
        command = ssh_command(identity)
        environment.pop("GIT_SSH", None)
        environment["GIT_SSH_COMMAND"] = command
    for item in items:
        target = destination(item["path"])
        if target.exists():
            if existing_remote(target) != item["url"]:
                raise ValueError(f"existing clone has a different origin: {item['path']}")
            print(f"ALREADY PRESENT {item['path']}  {identity_summary(target)[0]}")
            continue
        if not override and not home_rules_cover(target, item["url"]):
            target.rmdir()
            raise ValueError(
                f"no ~/.gitconfig rule gives an author for {item['path']}: add a folder or "
                "remote URL rule (tools/machine/gitconfig.example) or pass an explicit override"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", item["url"], str(target)], env=environment, check=True)
        if override:
            for key, value in (
                ("user.name", author_name.strip()),
                ("user.email", author_email.strip()),
                ("user.useConfigOnly", "true"),
                ("core.sshCommand", command),
            ):
                subprocess.run(["git", "-C", str(target), "config", "--local", key, value], check=True)
        print(f"CLONED          {item['path']}  {identity_summary(target)[0]}")
    return 0


def is_present(path: str) -> bool:
    try:
        return (destination(path) / ".git").exists()
    except ValueError:
        return False


def filter_project(items: list[dict[str, str]], project: str | None) -> list[dict[str, str]]:
    if project is None:
        return items
    return [item for item in items if item.get("project") == project]


def list_items(items: list[dict[str, str]], project: str | None, present: bool, missing: bool, as_json: bool) -> int:
    rows = [(item, is_present(item["path"])) for item in filter_project(items, project)]
    if present:
        rows = [row for row in rows if row[1]]
    if missing:
        rows = [row for row in rows if not row[1]]
    if as_json:
        print(json.dumps([
            {"path": i["path"], "url": i["url"], "project": i.get("project"), "present": here} for i, here in rows
        ], indent=2))
    elif project is None and not present and not missing:
        for item, _ in rows:
            print(f"{item['path']}  {item['url']}")
    else:
        for item, here in rows:
            print(f"{'present' if here else 'missing':<8}{item['path']}  {item.get('project', '-')}")
    return 0


GIT_TIMEOUT = 10


def local_git(repo: Path, *args: str) -> str:
    """Run a local Git command with a short timeout; raise ValueError with a short reason on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        raise ValueError("git timed out") from None
    if result.returncode:
        raise ValueError(result.stderr.strip().splitlines()[0] if result.stderr.strip() else "git failed")
    return result.stdout.strip()


def repo_state(repo: Path) -> dict:
    top = Path(local_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if top != repo.resolve():
        raise ValueError("not its own Git repository")
    state: dict = {}
    try:
        state["branch"] = local_git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    except ValueError:
        state["branch"] = "(detached)"
    state["changes"] = len([line for line in local_git(repo, "status", "--porcelain").splitlines() if line])
    try:
        behind, ahead = local_git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
        state["ahead"], state["behind"] = int(ahead), int(behind)
    except ValueError:
        pass  # no upstream: nothing to report
    try:
        state["last_commit"] = local_git(repo, "log", "-1", "--format=%cs")
    except ValueError:
        state["last_commit"] = None  # no commit yet
    return state


def git_roots() -> list[str]:
    """Git roots under repos/: depth 2, and depth 3 inside a group folder that holds no repository directly."""
    repos = WORK / "repos"
    roots: list[str] = []
    if repos.is_symlink() or not repos.is_dir():
        return roots

    def subdirs(folder: Path) -> list[Path]:
        try:
            return sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))
        except OSError:
            return []

    for group in subdirs(repos):
        children = subdirs(group)
        direct = [c for c in children if (c / ".git").exists()]
        if direct:
            roots.extend(c.relative_to(WORK).as_posix() for c in direct)
            continue
        for child in children:
            roots.extend(g.relative_to(WORK).as_posix() for g in subdirs(child) if (g / ".git").exists())
    return roots


def status(items: list[dict[str, str]], project: str | None, as_json: bool, whole_catalog: list[dict[str, str]]) -> int:
    report = []
    for item in filter_project(items, project):
        if not is_present(item["path"]):
            continue
        entry = {"path": item["path"], "project": item.get("project")}
        try:
            entry.update(repo_state(destination(item["path"])))
        except (ValueError, OSError) as exc:
            entry["error"] = str(exc)
        report.append(entry)
    listed = {item["path"] for item in whole_catalog}
    unlisted = [] if project is not None else [path for path in git_roots() if path not in listed]
    if as_json:
        print(json.dumps({"repositories": report, "not_in_catalog": unlisted}, indent=2))
        return 0
    for entry in report:
        if "error" in entry:
            print(f"ERROR  {entry['path']}: {entry['error']}")
            continue
        line = f"{entry['path']}  {entry['branch']}  changes={entry['changes']}"
        if "ahead" in entry:
            line += f"  ahead={entry['ahead']} behind={entry['behind']}"
        print(f"{line}  last={entry['last_commit'] or 'none'}")
    if project is None:
        print("\nnot in the catalog:")
        for path in unlisted:
            print(f"  {path}")
        if not unlisted:
            print("  (none)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("list")
    status_parser = commands.add_parser("status")
    for sub in (list_parser, status_parser):
        sub.add_argument("selector", nargs="?", help="client or repos/client/name")
        sub.add_argument("--project", help="only entries whose project is exactly this")
        sub.add_argument("--json", action="store_true", help="machine-readable output")
    only = list_parser.add_mutually_exclusive_group()
    only.add_argument("--present", action="store_true", help="only repositories present on this machine")
    only.add_argument("--missing", action="store_true", help="only repositories absent from this machine")
    commands.add_parser("check").add_argument("selector", nargs="?", help="client or repos/client/name")
    clone_parser = commands.add_parser("clone")
    clone_parser.add_argument("selector", help="one client or repos/client/name")
    clone_parser.add_argument("--identity", help="one-off override: absolute path to an approved SSH key")
    clone_parser.add_argument("--author-name", help="one-off override, with --identity")
    clone_parser.add_argument("--author-email", help="one-off override, with --identity")
    args = parser.parse_args()
    try:
        everything = catalog()
        items = selected(everything, args.selector)
        if args.command == "list":
            return list_items(items, args.project, args.present, args.missing, args.json)
        if args.command == "status":
            return status(items, args.project, args.json, everything)
        if args.command == "check":
            return check(items)
        return clone(items, args.identity, args.author_name, args.author_email)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
