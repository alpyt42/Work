"""Regression checks for the Claude Code SessionStart hook: short workspace state, local Git only, never fails."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "tools/machine/hooks/claude-session-start.py"
WORK_CONFIG = Path(__file__).resolve().parents[1] / "tools/machine/work_config.py"
WORD_CAP = 150


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
    )


def commit(repo: Path, name: str = "f.txt") -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


class SessionStartTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name).resolve()
        self.work = base / "Work"
        self.brain = self.work / "brain-acme"
        for repo in (self.work, self.brain):
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (self.brain / "AGENTS.md").write_text("# acme\n", encoding="utf-8")
        (self.brain / ".data").mkdir()
        (self.work / "tools/machine").mkdir(parents=True)
        (self.work / "tools/machine/work_config.py").write_text(WORK_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
        (self.work / ".gitignore").write_text("brain-acme/\n", encoding="utf-8")
        for repo in (self.work, self.brain):
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
        # Upstream for each repo: a bare clone used as remote.
        for repo in (self.work, self.brain):
            bare = base / f"{repo.name}.git"
            subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True, capture_output=True)
            git(repo, "remote", "add", "origin", str(bare))
            git(repo, "fetch", "-q", "origin")
            branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
            git(repo, "branch", "-q", f"--set-upstream-to=origin/{branch}")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_hook(self, stdin: str = "{}", root: Path | None = None, path: str | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root or self.work)}
        if path is not None:
            env["PATH"] = path
        result = subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr + result.stdout)
        self.assertLessEqual(len(result.stdout.split()), WORD_CAP)
        return result

    def test_clean(self) -> None:
        out = self.run_hook().stdout
        self.assertIn("default brain brain-acme", out)
        self.assertIn("all clean", out)
        self.assertIn("brain-state.py map", out)
        self.assertIn("brain-state.py brief", out)
        self.assertIn("brain-state.py find", out)

    def test_dirty_brain(self) -> None:
        (self.brain / "a.txt").write_text("a", encoding="utf-8")
        (self.brain / "b.txt").write_text("b", encoding="utf-8")
        out = self.run_hook().stdout
        self.assertIn("brain-acme: 2 uncommitted", out)
        self.assertNotIn("all clean", out)
        self.assertNotIn("a.txt", out)

    def test_commits_ahead(self) -> None:
        commit(self.brain, "c.txt")
        commit(self.brain, "d.txt")
        out = self.run_hook().stdout
        self.assertIn("brain-acme: 2 unpushed", out)
        self.assertNotIn("Work:", out)

    def test_no_upstream(self) -> None:
        git(self.brain, "branch", "--unset-upstream")
        commit(self.brain, "c.txt")
        out = self.run_hook().stdout
        self.assertIn("all clean", out)
        self.assertNotIn("unpushed", out)

    def test_work_dirty(self) -> None:
        (self.work / "x.txt").write_text("x", encoding="utf-8")
        self.assertIn("Work: 1 uncommitted", self.run_hook().stdout)

    def test_not_a_repo(self) -> None:
        subprocess.run(["rm", "-rf", str(self.brain / ".git")], check=True)
        out = self.run_hook().stdout
        self.assertIn("brain-acme", out)
        self.assertIn("brain-state.py map", out)

    def test_git_missing(self) -> None:
        out = self.run_hook(path="/nonexistent").stdout
        self.assertIn("default brain brain-acme", out)

    def test_empty_stdin(self) -> None:
        self.assertIn("brain-acme", self.run_hook(stdin="").stdout)

    def test_garbage_stdin(self) -> None:
        self.run_hook(stdin="not json {{{")

    def test_missing_root(self) -> None:
        out = self.run_hook(root=self.work / "nope").stdout
        self.assertIn("brain-state.py map", out)


if __name__ == "__main__":
    unittest.main()
