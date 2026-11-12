"""Tests for tools/machine/work.py (version, update --check | --dry-run | --apply) on temporary repositories."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools/machine/work.py"


class WorkUpdateCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "WORK_DIR"}
        self.env.update(GIT_CONFIG_GLOBAL=str(self.base / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="Ada", GIT_AUTHOR_EMAIL="ada@acme.example",
                        GIT_COMMITTER_NAME="Ada", GIT_COMMITTER_EMAIL="ada@acme.example")
        self.remote = self.base / "remote.git"
        self.seed = self.base / "seed"
        self.work = self.base / "Work"
        self.stub = self.base / "stub-update.sh"
        self.stub.write_text("#!/bin/bash\necho stub ran\necho done > update-ran.txt\n", encoding="utf-8")
        self.git(self.base, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.git(self.base, "clone", "-q", str(self.remote), str(self.seed))
        self.git(self.seed, "checkout", "-q", "-b", "main")
        self.commit(self.seed, "a.txt", "one\n", "feat: first")
        self.commit(self.seed, "b.txt", "one\n", "feat: second")
        self.git(self.seed, "push", "-q", "origin", "main")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, repo: Path, name: str, text: str, msg: str) -> None:
        (repo / name).write_text(text, encoding="utf-8")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", msg)

    def release(self, tag: str, message: str | None = "Changelog line") -> None:
        """Tag the seed's HEAD, push main and the tag (the way a maintainer publishes)."""
        if message is None:
            self.git(self.seed, "tag", tag)
        else:
            self.git(self.seed, "tag", "-a", tag, "-m", message)
        self.git(self.seed, "push", "-q", "origin", "main", tag)

    def clone_work(self) -> None:
        self.git(self.base, "clone", "-q", "-o", "starter", str(self.remote), str(self.work))

    def tool(self, *args: str, ok: int | None = 0) -> dict | subprocess.CompletedProcess:
        env = {**self.env, "WORK_DIR": str(self.work), "WORK_UPDATE_SCRIPT": str(self.stub)}
        proc = subprocess.run([sys.executable, str(TOOL), *args], env=env, capture_output=True, text=True)
        if ok is not None:
            self.assertEqual(proc.returncode, ok, proc.stdout + proc.stderr)
        return proc

    def check(self, *extra: str, ok: int | None = 0) -> dict:
        proc = self.tool("update", "--check", "--json", *extra, ok=ok)
        return json.loads(proc.stdout)

    def test_unreleased(self) -> None:
        self.clone_work()
        version = json.loads(self.tool("version", "--json").stdout)
        self.assertIsNone(version["current"])
        self.assertEqual((version["branch"], version["remote"]), ("main", "starter"))
        rep = self.check()
        self.assertEqual((rep["state"], rep["current"], rep["latest"]), ("up-to-date", None, None))

    def test_up_to_date(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        rep = self.check()
        self.assertEqual((rep["state"], rep["current"], rep["latest"]), ("up-to-date", "v1.0.0", "v1.0.0"))
        self.assertEqual(json.loads(self.tool("version", "--json").stdout)["current"], "v1.0.0")

    def test_minor_available(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "c.txt", "x\n", "feat: add c")
        self.commit(self.seed, "a.txt", "two\n", "fix: change a")
        self.release("v1.1.0", "Added c.\nFixed a.")
        # without fetching, the release is unknown
        self.assertEqual(self.check("--no-fetch")["state"], "up-to-date")
        rep = self.check()
        self.assertEqual((rep["state"], rep["kind"], rep["latest"]), ("available", "minor", "v1.1.0"))
        self.assertEqual(rep["commits"], ["fix: change a", "feat: add c"])
        self.assertEqual((rep["commits_total"], rep["files"], rep["reasons"]), (2, 2, []))
        self.assertEqual(rep["notes"], "Added c.\nFixed a.")
        self.assertTrue(rep["fetched"])
        human = self.tool("update", "--check").stdout
        self.assertIn("v1.1.0 available (minor)", human)

    def test_patch_and_lightweight_tag_has_no_notes(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "a.txt", "two\n", "fix: a")
        self.release("v1.0.1", None)
        rep = self.check()
        self.assertEqual((rep["kind"], rep["notes"]), ("patch", None))

    def test_major_blocked(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "c.txt", "x\n", "feat!: rework")
        self.release("v2.0.0")
        rep = self.check()
        self.assertEqual((rep["state"], rep["kind"]), ("blocked", "major"))
        self.assertIn("major", rep["reasons"][0])
        self.tool("update", "--apply", ok=1)
        self.assertFalse((self.work / "c.txt").exists())

    def test_diverged_blocked(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.work, "local.txt", "mine\n", "feat: local")
        self.commit(self.seed, "c.txt", "x\n", "feat: c")
        self.release("v1.1.0")
        rep = self.check()
        self.assertEqual(rep["state"], "blocked")
        self.assertIn("diverged", rep["reasons"][0])

    def test_modified_tracked_file_blocks_only_when_touched(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "a.txt", "two\n", "fix: a")
        self.release("v1.0.1")
        (self.work / "b.txt").write_text("local edit\n", encoding="utf-8")  # tracked, untouched by the update
        (self.work / "untracked.txt").write_text("new\n", encoding="utf-8")
        self.assertEqual(self.check()["state"], "available")
        (self.work / "a.txt").write_text("local edit\n", encoding="utf-8")  # tracked, changed by the update
        rep = self.check("--no-fetch")
        self.assertEqual(rep["state"], "blocked")
        self.assertIn("a.txt", rep["reasons"][0])

    def test_detached_head_blocked(self) -> None:
        self.clone_work()
        self.git(self.work, "checkout", "-q", "--detach")
        rep = self.check()
        self.assertEqual(rep["state"], "blocked")
        self.assertIn("detached", rep["reasons"][0])

    def test_fetch_failure_is_an_error(self) -> None:
        self.clone_work()
        self.git(self.work, "remote", "set-url", "starter", str(self.base / "missing.git"))
        proc = self.tool("update", "--check", "--json", ok=1)
        rep = json.loads(proc.stdout)
        self.assertEqual(rep["state"], "error")
        self.assertTrue(rep["error"])
        self.assertNotIn("Traceback", proc.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash is required for the update script")
    def test_apply_fast_forwards_and_runs_the_script(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "c.txt", "x\n", "feat: c")
        self.release("v1.1.0")
        proc = self.tool("update", "--apply", "--to", "v1.1.0", "--json")
        rep = json.loads(proc.stdout)
        self.assertTrue(rep["applied"])
        self.assertEqual((rep["from"], rep["to"]), ("v1.0.0", "v1.1.0"))
        self.assertEqual(rep["update_script"]["output_tail"], ["stub ran"])
        self.assertTrue((self.work / "c.txt").exists())
        self.assertTrue((self.work / "update-ran.txt").exists())
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), self.git(self.seed, "rev-parse", "HEAD"))
        self.assertEqual(self.check()["state"], "up-to-date")
        self.assertEqual(self.tool("update", "--apply", "--json").returncode, 0)  # nothing to do

    def test_apply_to_mismatch_refused(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "c.txt", "x\n", "feat: c")
        self.release("v1.1.0")
        proc = self.tool("update", "--apply", "--to", "v1.0.5", "--json", ok=1)
        self.assertIn("v1.1.0", json.loads(proc.stdout)["reasons"][0])
        self.assertFalse((self.work / "c.txt").exists())
        self.tool("update", "--apply", "--to", "1.1", ok=2)

    def test_dry_run_changes_nothing(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.seed, "c.txt", "x\n", "feat: c")
        self.release("v1.1.0")
        before = self.git(self.work, "rev-parse", "HEAD")
        rep = json.loads(self.tool("update", "--dry-run", "--json").stdout)
        self.assertTrue(rep["would_apply"])
        self.assertEqual(len(rep["plan"]), 2)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), before)
        self.assertFalse((self.work / "c.txt").exists())
        self.assertFalse((self.work / "update-ran.txt").exists())

    # --- release --next / --notes

    def next_release(self) -> dict:
        return json.loads(self.tool("release", "--next", "--json").stdout)

    def test_release_no_tag_is_first_minor(self) -> None:
        self.clone_work()
        rel = self.next_release()
        self.assertEqual((rel["current"], rel["next"], rel["kind"], rel["commits"]), (None, "v0.1.0", "minor", 2))

    def test_release_kinds(self) -> None:
        self.release("v1.2.3")
        self.clone_work()
        self.assertIsNone(self.next_release()["next"])  # no commit since the tag
        self.commit(self.work, "a.txt", "2\n", "docs: reword")
        self.assertEqual(self.next_release()["next"], "v1.2.4")
        self.commit(self.work, "a.txt", "3\n", "fix(core): patch it")
        self.assertEqual(self.next_release()["kind"], "patch")
        self.commit(self.work, "a.txt", "4\n", "feat: add it")
        rel = self.next_release()
        self.assertEqual((rel["next"], rel["kind"], rel["commits"], rel["current"]), ("v1.3.0", "minor", 3, "v1.2.3"))
        self.commit(self.work, "a.txt", "5\n", "refactor!: drop it")
        self.assertEqual(self.next_release()["next"], "v2.0.0")

    def test_release_breaking_footer(self) -> None:
        self.release("v1.2.3")
        self.clone_work()
        self.commit(self.work, "a.txt", "2\n", "feat: new layout\n\nBREAKING CHANGE: layout moved")
        self.assertEqual(self.next_release()["next"], "v2.0.0")

    def test_release_notes_grouping(self) -> None:
        self.release("v1.0.0")
        self.clone_work()
        self.commit(self.work, "a.txt", "2\n", "feat(ui): add panel")
        self.commit(self.work, "a.txt", "3\n", "fix: close leak")
        self.commit(self.work, "a.txt", "4\n", "chore: tidy")
        self.commit(self.work, "a.txt", "5\n", "feat!: rename")
        rel = json.loads(self.tool("release", "--notes", "--json").stdout)
        notes = rel["notes"]
        self.assertEqual(rel["next"], "v2.0.0")
        self.assertLess(notes.index("### Breaking changes"), notes.index("### Features"))
        self.assertLess(notes.index("### Features"), notes.index("### Fixes"))
        self.assertLess(notes.index("### Fixes"), notes.index("### Other changes"))
        self.assertIn("- **ui**: add panel", notes)
        self.assertIn("- rename", notes)
        self.assertNotIn("feat", notes.replace("### Features", ""))
        self.assertNotIn("First release", notes)

    def test_release_notes_first_release_and_empty(self) -> None:
        self.clone_work()
        notes = json.loads(self.tool("release", "--notes", "--json").stdout)["notes"]
        self.assertTrue(notes.startswith("First release."))
        self.assertIn("### Features", notes)
        self.assertIn("- first", notes)
        self.git(self.work, "tag", "-a", "v0.1.0", "-m", "x")
        self.assertEqual(json.loads(self.tool("release", "--notes", "--json").stdout)["notes"], "")
        self.assertEqual(self.tool("release", "--notes").returncode, 0)


if __name__ == "__main__":
    unittest.main()
