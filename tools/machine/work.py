#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Tell whether a newer release of the Work workspace exists, and apply it.

Usage:
  work.py version [--json]
  work.py update --check [--no-fetch] [--json]
  work.py update --dry-run [--no-fetch] [--json]
  work.py update --apply [--to vX.Y.Z] [--no-fetch] [--json]
  work.py release --next | --notes [--json]

A release is a Git tag `v<major>.<minor>.<patch>` on the upstream remote of the current branch. The current
version is the highest such tag that is an ancestor of HEAD (none: "unreleased", a normal state). A newer
release is available when its version is higher and HEAD is an ancestor of its commit (fast-forward).

`update --check` fetches the tags of the upstream remote (20 s, never prompts) unless --no-fetch, then reports
`state`: up-to-date | available | blocked | error. It is blocked by local commits (diverged), by tracked files
modified in the working tree that the update also changes, by a new major version (it needs a migration that
does not exist yet), by a detached HEAD or by a missing upstream. Untracked files and modified files the update
does not touch never block. `--dry-run` adds what `--apply` would do and changes nothing. `--apply` re-checks,
refuses unless the state is available (`--to` must equal the latest release), runs `git merge --ff-only <tag>`,
then `tools/machine/update.sh` (skipped with a note when bash cannot run it). It never commits, pushes, rebases,
resets or stashes, and never touches the brains (separate repositories).

`release` is read-only and made for CI (full history, no Git identity): `--next` derives the next version from the
Conventional Commits since the last release tag reachable from HEAD (`!` after the type or a `BREAKING CHANGE:`
footer: major; else `feat`: minor; else any commit: patch; no tag yet: v0.1.0; no new commit: `next` null) and
`--notes` prints the Markdown release notes of the same range. It never fetches and never creates or pushes a tag.

Exit status: 0 success or nothing to do, 1 refused or failed, 2 usage error. Environment: WORK_DIR selects
another workspace; WORK_UPDATE_SCRIPT another update script (absolute, or relative to the workspace).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parents[2])).resolve()
FETCH_TIMEOUT = 20
GIT_TIMEOUT = 30
SCRIPT_TIMEOUT = 600
MAX_NOTE_LINES = 20
MAX_COMMITS = 15
TAIL_LINES = 15
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
STALE_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH")
ENV = {**{k: v for k, v in os.environ.items() if k not in STALE_ENV},
       "GIT_TERMINAL_PROMPT": "0", "GIT_MERGE_AUTOEDIT": "no", "LC_ALL": "C"}


def run(cmd: list[str], timeout: int = GIT_TIMEOUT, cwd: Path | None = None) -> tuple[int, str]:
    """Run a command without shell or stdin; return (exit code, stdout+stderr). 124 on timeout, 127 if missing."""
    try:
        proc = subprocess.run(cmd, cwd=cwd or ROOT, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, text=True, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, proc.stdout


def git(*args: str, timeout: int = GIT_TIMEOUT) -> tuple[int, str]:
    return run(["git", *args], timeout)


def out(*args: str) -> str | None:
    rc, text = git(*args)
    return text.strip() if rc == 0 else None


def parse_tag(tag: str) -> tuple[int, int, int] | None:
    m = TAG_RE.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def tag_name(version: tuple[int, int, int]) -> str:
    return "v%d.%d.%d" % version


def is_ancestor(a: str, b: str) -> bool:
    return git("merge-base", "--is-ancestor", a, b)[0] == 0


def highest(tags: list[str]) -> str | None:
    valid = [t for t in tags if parse_tag(t)]
    return max(valid, key=parse_tag) if valid else None


def repo_state() -> dict:
    """Branch, upstream remote and HEAD of the workspace (local Git only)."""
    state = {"head": out("rev-parse", "--short", "HEAD"), "branch": None, "remote": None, "upstream": None}
    rc, branch = git("symbolic-ref", "--short", "-q", "HEAD")
    if rc == 0:
        state["branch"] = branch.strip()
        state["upstream"] = out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if state["upstream"]:
            state["remote"] = out("config", f"branch.{state['branch']}.remote")
    return state


def current_release() -> str | None:
    rc, text = git("tag", "--merged", "HEAD", "--list", "v*")
    return highest(text.split()) if rc == 0 else None


def tag_notes(tag: str) -> str | None:
    if out("for-each-ref", f"refs/tags/{tag}", "--format=%(objecttype)") != "tag":
        return None  # lightweight tag: its "message" is the commit's, not a changelog
    text = out("for-each-ref", f"refs/tags/{tag}", "--format=%(contents)")
    lines = text.splitlines() if text else []
    lines = lines[:MAX_NOTE_LINES]
    return "\n".join(lines) or None


def kind_of(current: tuple[int, int, int] | None, latest: tuple[int, int, int]) -> str:
    if current is None:
        return "minor"  # the first release is not a migration
    if latest[0] != current[0]:
        return "major"
    return "minor" if latest[1] != current[1] else "patch"


def report(fetch: bool = True) -> dict:
    """The full update report; never raises."""
    info = repo_state()
    rep = {"state": "up-to-date", "current": None, "latest": None, "kind": None, "notes": None, "commits": [],
           "commits_total": 0, "files": 0, "reasons": [], "error": None, "fetched": False,
           "branch": info["branch"], "remote": info["remote"], "head": info["head"]}
    if info["head"] is None:
        return {**rep, "state": "error", "error": "not a Git repository", "reasons": ["not a Git repository"]}
    cur = current_release()
    rep["current"] = cur
    if info["branch"] is None:
        rep["state"], rep["reasons"] = "blocked", ["detached HEAD: check out a branch that tracks the upstream"]
        return rep
    if not info["remote"]:
        rep["state"], rep["reasons"] = "blocked", ["no upstream remote for the current branch"]
        return rep
    if fetch:
        rc, text = git("fetch", "--tags", "--quiet", info["remote"], timeout=FETCH_TIMEOUT)
        if rc != 0:
            reason = "fetch timed out" if rc == 124 else "fetch failed: " + (text.strip().splitlines() or ["?"])[-1][:160]
            return {**rep, "state": "error", "error": reason, "reasons": [reason]}
        rep["fetched"] = True
    rc, text = git("tag", "--list", "v*")
    latest = highest(text.split()) if rc == 0 else None
    if latest is None or (cur and parse_tag(latest) <= parse_tag(cur)):
        rep["latest"] = cur
        return rep
    rep["latest"] = latest
    rep["kind"] = kind_of(parse_tag(cur) if cur else None, parse_tag(latest))
    rep["notes"] = tag_notes(latest)
    ref = f"refs/tags/{latest}^{{commit}}"
    ff = is_ancestor("HEAD", ref)
    reasons = []
    if not ff:
        reasons.append(f"HEAD is not an ancestor of {latest}: local commits (diverged), no fast-forward possible")
    else:
        rc, text = git("log", "--format=%s", f"-{MAX_COMMITS}", f"HEAD..{ref}")
        rep["commits"] = text.splitlines() if rc == 0 else []
        rep["commits_total"] = int(out("rev-list", "--count", f"HEAD..{ref}") or 0)
        changed = (out("diff", "--name-only", "HEAD", ref) or "").splitlines()
        rep["files"] = len(changed)
        dirty = set((out("diff", "--name-only", "HEAD") or "").splitlines())
        clash = sorted(dirty & set(changed))
        if clash:
            shown = ", ".join(clash[:5]) + (f" (+{len(clash) - 5} more)" if len(clash) > 5 else "")
            reasons.append(f"modified tracked files the update also changes: {shown}")
    if rep["kind"] == "major":
        reasons.append("new major version: it needs a migration that does not exist yet")
    rep["state"] = "blocked" if reasons else "available"
    rep["reasons"] = reasons
    return rep


def plan_for(rep: dict, script: str) -> list[str]:
    if rep["state"] != "available":
        return []
    return [f"git merge --ff-only {rep['latest']} on branch {rep['branch']}", f"run {script} from the Work root"]


def update_script() -> Path:
    raw = os.environ.get("WORK_UPDATE_SCRIPT")
    path = Path(raw) if raw else Path("tools/machine/update.sh")
    return path if path.is_absolute() else ROOT / path


def run_update_script() -> dict:
    script = update_script()
    res = {"ran": False, "skipped": None, "exit_code": None, "output_tail": []}
    bash = shutil.which("bash")
    if not script.is_file():
        res["skipped"] = "update script not found"
    elif not bash:
        res["skipped"] = "bash not found: run tools/machine/update.sh yourself (Git Bash or WSL)"
    else:
        rc, text = run([bash, str(script)], SCRIPT_TIMEOUT)
        res.update(ran=True, exit_code=rc, output_tail=text.strip().splitlines()[-TAIL_LINES:])
    return res


def apply(rep: dict, to: str | None) -> tuple[dict, int]:
    rep = {**rep, "applied": False, "from": rep["current"], "to": None, "update_script": None}
    if rep["state"] == "error" or rep["state"] == "blocked":
        return rep, 1
    if rep["state"] == "up-to-date":
        return rep, 0
    if to and to != rep["latest"]:
        rep["state"] = "blocked"
        rep["reasons"] = [f"--to {to} is not the latest available release ({rep['latest']}): check again"]
        return rep, 1
    rc, text = git("merge", "--ff-only", f"refs/tags/{rep['latest']}^{{commit}}")
    if rc != 0:
        rep["state"] = "error"
        rep["error"] = "merge failed: " + (text.strip().splitlines() or ["?"])[-1][:160]
        rep["reasons"] = [rep["error"]]
        return rep, 1
    rep.update(applied=True, to=rep["latest"], head=out("rev-parse", "--short", "HEAD"))
    rep["update_script"] = run_update_script()
    ok = rep["update_script"]["exit_code"] in (None, 0)
    return rep, 0 if ok else 1


def human(rep: dict) -> str:
    lines = []
    cur = rep["current"] or "unreleased"
    if rep["state"] == "error":
        return f"Error: {rep['error']}"
    if rep["state"] == "up-to-date":
        lines.append(f"Up to date ({cur}).")
    else:
        verb = "available" if rep["state"] == "available" else "blocked"
        lines.append(f"{rep['latest']} {verb} ({rep['kind']}), current: {cur}.")
        lines += [f"- {r}" for r in rep["reasons"]]
        if rep["commits_total"]:
            lines.append(f"{rep['commits_total']} commits, {rep['files']} files changed:")
            lines += [f"  {s}" for s in rep["commits"]]
            if rep["commits_total"] > len(rep["commits"]):
                lines.append(f"  (+{rep['commits_total'] - len(rep['commits'])} more)")
        if rep["notes"]:
            lines += ["Notes:", *[f"  {n}" for n in rep["notes"].splitlines()]]
    for step in rep.get("plan", []):
        lines.append(f"Would: {step}")
    if rep.get("applied"):
        lines.append(f"Updated {rep['from'] or 'unreleased'} -> {rep['to']}.")
        us = rep["update_script"]
        if us["skipped"]:
            lines.append(f"update.sh skipped: {us['skipped']}")
        else:
            lines += [f"update.sh exit {us['exit_code']}:", *[f"  {t}" for t in us["output_tail"]]]
    return "\n".join(lines)


CC_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?(!)?:\s*(.+)$")
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.M)
GROUPS = (("breaking", "Breaking changes"), ("feat", "Features"), ("fix", "Fixes"), ("other", "Other changes"))
MAX_NOTE_ITEMS = 50


def release_commits() -> tuple[str | None, list[dict]]:
    """The last release tag reachable from HEAD and the commits since it, parsed as Conventional Commits."""
    cur = current_release()
    rc, text = git("log", "--no-merges", "--format=%s%x1f%b%x1e", f"{cur}..HEAD" if cur else "HEAD")
    commits = []
    for record in (text.split("\x1e") if rc == 0 else []):
        if not record.strip():
            continue
        subject, _, body = record.strip("\n").partition("\x1f")
        m = CC_RE.match(subject.strip())
        ctype, scope, bang, title = (m[1].lower(), m[2], bool(m[3]), m[4]) if m else (None, None, False, subject.strip())
        breaking = bang or bool(BREAKING_RE.search(body))
        group = "breaking" if breaking else "feat" if ctype == "feat" else "fix" if ctype == "fix" else "other"
        commits.append({"type": ctype, "scope": scope, "title": title, "group": group, "breaking": breaking,
                        "feat": ctype == "feat"})
    return cur, commits


def next_release() -> dict:
    cur, commits = release_commits()
    res = {"current": cur, "next": None, "kind": None, "commits": len(commits)}
    if not commits:
        return res
    if cur is None:
        res.update(next="v0.1.0", kind="minor")
        return res
    major, minor, patch = parse_tag(cur)
    if any(c["breaking"] for c in commits):
        res.update(next=tag_name((major + 1, 0, 0)), kind="major")
    elif any(c["feat"] for c in commits):
        res.update(next=tag_name((major, minor + 1, 0)), kind="minor")
    else:
        res.update(next=tag_name((major, minor, patch + 1)), kind="patch")
    return res


def release_notes() -> tuple[dict, str]:
    info = next_release()
    _, commits = release_commits()
    if not commits:
        return info, ""
    lines = [] if info["current"] else ["First release.", ""]
    budget = MAX_NOTE_ITEMS
    for key, heading in GROUPS:
        items = [c for c in commits if c["group"] == key]
        if not items:
            continue
        lines += [f"### {heading}", ""]
        for c in items[:budget]:
            lines.append(f"- **{c['scope']}**: {c['title']}" if c["scope"] else f"- {c['title']}")
        if len(items) > budget:
            lines.append(f"- +{len(items) - budget} more")
        budget = max(budget - len(items), 0)
        lines.append("")
    return info, "\n".join(lines).rstrip() + "\n"


def cmd_release(args) -> int:
    if args.next:
        info = next_release()
        text = f"{info['next']} ({info['kind']}, {info['commits']} commits since {info['current'] or 'the start'})" \
            if info["next"] else f"No release: no new commit since {info['current'] or 'the start'}."
    else:
        info, notes = release_notes()
        info["notes"] = notes
        text = notes.rstrip("\n") or "No release: no new commit."
    print(json.dumps(info, indent=2) if args.json else text)
    return 0


def cmd_version(args) -> int:
    info = repo_state()
    data = {"current": current_release(), "head": info["head"], "branch": info["branch"], "remote": info["remote"]}
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"{data['current'] or 'unreleased'} ({data['head']}) on {data['branch'] or 'detached HEAD'}"
              f", upstream: {data['remote'] or 'none'}")
    return 0 if data["head"] else 1


def cmd_update(args) -> int:
    rep = report(fetch=not args.no_fetch)
    code = 1 if rep["state"] == "error" else 0
    if args.dry_run:
        rep["plan"] = plan_for(rep, "tools/machine/update.sh")
        rep["would_apply"] = rep["state"] == "available"
    elif args.apply:
        rep, code = apply(rep, args.to)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(human(rep))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check and apply Work workspace releases.")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("version", help="current release, HEAD, branch, upstream remote")
    v.add_argument("--json", action="store_true")
    u = sub.add_parser("update", help="check for, preview or apply a newer release")
    mode = u.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report the state of the update")
    mode.add_argument("--dry-run", action="store_true", help="report and say what --apply would do")
    mode.add_argument("--apply", action="store_true", help="fast-forward to the latest release and run update.sh")
    u.add_argument("--to", metavar="vX.Y.Z", help="with --apply: the release the caller showed (must be the latest)")
    u.add_argument("--no-fetch", action="store_true", help="use the tags already fetched")
    u.add_argument("--json", action="store_true")
    r = sub.add_parser("release", help="next version and release notes from Conventional Commits (read-only, CI)")
    what = r.add_mutually_exclusive_group(required=True)
    what.add_argument("--next", action="store_true", help="the next version, or null when nothing is new")
    what.add_argument("--notes", action="store_true", help="the Markdown release notes since the last tag")
    r.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "release":
        return cmd_release(args)
    if args.command == "update" and args.to and not args.apply:
        parser.error("--to goes with --apply")
    if args.command == "update" and args.to and not parse_tag(args.to):
        parser.error("--to must look like vX.Y.Z")
    return cmd_version(args) if args.command == "version" else cmd_update(args)


if __name__ == "__main__":
    sys.exit(main())
