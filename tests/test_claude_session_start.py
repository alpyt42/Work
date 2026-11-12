"""Regression checks for the Claude Code SessionStart hook: short workspace state, local Git only, never fails.

The setup block itself (what setup.py reports) is tested in test_setup.py; here, stub setup.py files check how the
hook runs it: after the state lines, dropped when it fails or is too slow.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "tools/machine/hooks/claude-session-start.py"
WORK_CONFIG = Path(__file__).resolve().parents[1] / "tools/machine/work_config.py"
WORD_CAP = 150
SETUP_WORD_CAP = 500


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
        # Like the real Work: the hook imports work_config.py, which writes __pycache__/ unless PYTHONDONTWRITEBYTECODE is set (CI).
        (self.work / ".gitignore").write_text("brain-acme/\n__pycache__/\n", encoding="utf-8")
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
        state, _, setup = result.stdout.partition("\nSetup")
        self.assertLessEqual(len(state.split()), WORD_CAP)
        self.assertLessEqual(len(setup.split()), SETUP_WORD_CAP + 10)
        return result

    def write_setup(self, body: str) -> None:
        """A stub tools/machine/setup.py whose session_block runs `body`."""
        code = "import time\n\ndef session_block(root):\n" + "".join(f"    {line}\n" for line in body.splitlines())
        (self.work / "tools/machine/setup.py").write_text(code, encoding="utf-8")

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

    def test_no_setup_script_prints_nothing_about_setup(self) -> None:
        self.assertNotIn("Setup", self.run_hook().stdout)

    def test_setup_block_comes_after_the_state_lines(self) -> None:
        self.write_setup('return "Setup incomplete: ask for `artifactsDir`."')
        lines = self.run_hook().stdout.splitlines()
        self.assertEqual(lines[-1], "Setup incomplete: ask for `artifactsDir`.")
        self.assertTrue(lines[0].startswith("Workspace: default brain brain-acme"))
        self.assertIn("brain-state.py map", lines[-2])

    def test_empty_setup_block_prints_nothing(self) -> None:
        self.write_setup('return ""')
        out = self.run_hook().stdout
        self.assertNotIn("Setup", out)
        self.assertTrue(out.rstrip().endswith("for each kind of question."))

    def test_failing_setup_prints_nothing_about_setup(self) -> None:
        self.write_setup('raise RuntimeError("Setup exploded")')
        out = self.run_hook().stdout
        self.assertNotIn("Setup", out)
        self.assertIn("default brain brain-acme", out)

    def test_broken_setup_script_prints_nothing_about_setup(self) -> None:
        (self.work / "tools/machine/setup.py").write_text("def session_block(root):\n    return (\n", encoding="utf-8")
        self.assertNotIn("Setup", self.run_hook().stdout)

    def test_slow_setup_is_dropped_within_the_budget(self) -> None:
        self.write_setup('time.sleep(6)\nreturn "Setup incomplete: too late."')
        started = time.monotonic()
        out = self.run_hook().stdout
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotIn("Setup", out)
        self.assertIn("default brain brain-acme", out)


if __name__ == "__main__":
    unittest.main()
