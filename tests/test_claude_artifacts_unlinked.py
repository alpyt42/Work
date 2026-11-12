"""The Claude Code guard refuses writes into a stale artifacts/ folder while it is not linked to `artifactsDir`."""

import json
import unittest
from pathlib import Path

from test_claude_bash_guard import GuardTestCase

MESSAGE = "is not linked yet to the artifacts folder"

WRITES = [
    "cp report.pdf artifacts/acme-report/",
    "cp -t artifacts/x a.txt b.txt",
    "mv a.txt artifacts/a.txt",
    "mv a.txt artifacts/archive/",
    "rsync -a out/ artifacts/acme-report/",
    "ditto out artifacts/acme-report",
    "install -m 644 a.txt artifacts/a.txt",
    "ln -s ../a.txt artifacts/link",
    "echo hi > artifacts/a.txt",
    "echo hi >> artifacts/a.txt",
    "echo hi &> artifacts/a.txt",
    "echo hi >| artifacts/a.txt",
    "echo hi 2> artifacts/err.log",
    "echo hi | tee artifacts/a.txt",
    "echo hi | tee -a other.txt artifacts/a.txt",
    "mkdir -p artifacts/new/deeper",
    "touch artifacts/a.txt",
    "curl -o artifacts/a.html https://example.test",
    "tool --output artifacts/a.json",
    "tool --output=artifacts/a.json",
    "tool --out artifacts/a.json",
    "tool --output-dir artifacts/render",
    "tool --outdir=artifacts/render",
    "cp a.txt ./artifacts/../artifacts/a.txt",
    "cp a.txt @WORK@/artifacts/a.txt",
    "(cd repos/demo && cp a.txt ../../artifacts/a.txt)",
    "bash -c 'echo hi > artifacts/a.txt'",
    "cd artifacts && touch a.txt",
    "cd artifacts/acme-report && echo hi > a.txt",
]
READS = [
    "cat artifacts/a.txt",
    "ls -la artifacts/",
    "open artifacts/acme-report",
    "grep -rn foo artifacts/",
    "head -5 artifacts/a.txt",
    "diff artifacts/a.txt other.txt",
    "cp artifacts/a.txt /tmp/copy.txt",
    "cd artifacts && ls",
    "echo hi > other.txt 2>&1",
    "ls artifacts 2>&1",
    "cat artifacts/a.txt > repos/out.txt",
    "mkdir -p agents/new && touch agents/x",
]


class UnlinkedArtifactsTest(GuardTestCase):
    def work_root(self, name: str, setting: object = None) -> Path:
        work = self.home / name
        (work / "tools/machine").mkdir(parents=True)
        (work / "tools/machine/work_config.py").write_text("# fictitious\n", encoding="utf-8")
        (work / "artifacts/acme-report").mkdir(parents=True)
        (work / "repos/demo").mkdir(parents=True)
        if setting is not None:
            (work / "work-config.local.json").write_text(json.dumps({"version": 1, "artifactsDir": setting}), encoding="utf-8")
        self.synced = self.home / f"{name}-synced"
        self.synced.mkdir(exist_ok=True)
        return work

    def tool(self, tool: str, path: str, work: Path, key: str = "file_path"):
        return self.run_hook(None, cwd=work, raw=json.dumps({"tool_name": tool, "tool_input": {key: path}, "cwd": str(work)}))

    def test_bash_writes_are_refused_with_the_configured_path(self) -> None:
        work = self.work_root("unlinked-work")
        synced = self.synced
        (work / "work-config.local.json").write_text(json.dumps({"artifactsDir": str(synced)}), encoding="utf-8")
        for command in WRITES:
            with self.subTest(command=command):
                result = self.assert_blocked(command.replace("@WORK@", str(work)), MESSAGE, cwd=work)
                self.assertIn(str(synced), result.stderr)

    def test_the_corrected_path_keeps_the_relative_part(self) -> None:
        work = self.work_root("corrected-work", "../corrected-sync")
        result = self.assert_blocked("cp a.txt artifacts/acme-report/a.txt", MESSAGE, cwd=work)
        self.assertIn(f"write to {self.home}/corrected-sync/acme-report/a.txt instead", result.stderr)

    def test_file_tools_are_refused(self) -> None:
        work = self.work_root("tools-work", "~/tools-sync")
        cases = [("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")]
        for tool, key in cases:
            for path in (f"{work}/artifacts/acme-report/a.md", "artifacts/a.md", "./artifacts/../artifacts/a.md", f"{work}/repos/../artifacts/a.md"):
                with self.subTest(tool=tool, path=path):
                    result = self.tool(tool, path, work, key)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(MESSAGE, result.stderr)
                    self.assertIn(f"{self.home}/tools-sync", result.stderr)
            for path in (f"{work}/repos/demo/a.md", "repos/a.md", f"{self.home}/tools-sync/a.md", f"{work}/artifacts-notes.md"):
                with self.subTest(tool=tool, allowed=path):
                    self.assertEqual(self.tool(tool, path, work, key).returncode, 0)

    def test_reads_and_other_targets_are_allowed(self) -> None:
        work = self.work_root("reads-work")
        (work / "work-config.local.json").write_text(json.dumps({"artifactsDir": str(self.synced)}), encoding="utf-8")
        for command in READS:
            with self.subTest(command=command):
                self.assert_allowed(command, cwd=work)

    def test_writes_to_the_configured_folder_are_allowed(self) -> None:
        work = self.work_root("configured-work", "../configured-synced")
        for command in (f"cp a.txt {self.home}/configured-synced/a.txt", f"echo hi > {self.home}/configured-synced/a.txt", "mkdir -p ../configured-synced/new"):
            with self.subTest(command=command):
                self.assert_allowed(command, cwd=work)
        self.assertEqual(self.tool("Write", f"{self.home}/configured-synced/a.md", work).returncode, 0)

    def test_a_linked_folder_is_allowed(self) -> None:
        work = self.home / "linked-work"
        (work / "tools/machine").mkdir(parents=True)
        (work / "tools/machine/work_config.py").write_text("# fictitious\n", encoding="utf-8")
        target = self.home / "linked-sync"
        target.mkdir()
        (work / "artifacts").symlink_to(target)
        (work / "work-config.local.json").write_text(json.dumps({"artifactsDir": str(target)}), encoding="utf-8")
        self.assert_allowed("cp a.txt artifacts/a.txt", cwd=work)
        self.assert_allowed("echo hi > artifacts/a.txt", cwd=work)
        self.assertEqual(self.tool("Write", f"{work}/artifacts/a.md", work).returncode, 0)

    def test_inactive_settings_are_allowed(self) -> None:
        cases = {"unset": None, "equal": "artifacts", "equal-absolute": "abs", "empty": "", "wrong-type": 3}
        for name, setting in cases.items():
            with self.subTest(setting=name):
                work = self.work_root(f"inactive-{name}")
                if setting is not None:
                    value = str(work / "artifacts") if setting == "abs" else setting
                    (work / "work-config.local.json").write_text(json.dumps({"artifactsDir": value}), encoding="utf-8")
                self.assert_allowed("cp a.txt artifacts/a.txt", cwd=work)
                self.assert_allowed("echo hi > artifacts/a.txt", cwd=work)
                self.assertEqual(self.tool("Write", f"{work}/artifacts/a.md", work).returncode, 0)

    def test_a_missing_artifacts_folder_is_refused(self) -> None:
        work = self.work_root("missing-work", "../missing-sync")
        (work / "artifacts/acme-report").rmdir()
        (work / "artifacts").rmdir()
        self.assert_blocked("mkdir artifacts", MESSAGE, cwd=work)
        self.assert_blocked("cp a.txt artifacts/a.txt", MESSAGE, cwd=work)
        result = self.tool("Write", f"{work}/artifacts/a.md", work)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("work_config.py artifacts-dir", result.stderr)
        self.assertIn("artifacts-link", result.stderr)
        self.assert_allowed("ls artifacts", cwd=work)

    def test_existing_protections_are_unchanged(self) -> None:
        work = self.work_root("kept-work", "../kept-sync")
        self.assert_blocked("rm -rf artifacts/x", "artifacts/ is protected", cwd=work)
        self.assert_blocked("mv artifacts/acme-report /tmp/y", "artifacts/ is protected", cwd=work)


if __name__ == "__main__":
    unittest.main()
