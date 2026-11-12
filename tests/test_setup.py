"""Tests for the machine setup checklist (tools/machine/setup.py) and its block in the SessionStart hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools/machine/setup.py"
WORK_CONFIG = REPO / "tools/machine/work_config.py"
HOOK = REPO / "tools/machine/hooks/claude-session-start.py"
EMPTY_BOUNDARY = {"allow": [], "description": "", "email": "", "remote": "", "scope": "", "version": 1}
BRAIN_SETTINGS = ("owner", "scope", "description", "remote", "email")
TRANSCRIPTS_DEFAULT = "Documents/Transcripts"


class SetupTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve()
        self.work = self.home / "Work"
        self.work.mkdir()
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        (bin_dir / "uv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")  # found on PATH, never run
        (bin_dir / "uv").chmod(0o755)
        (self.home / "gitconfig").write_text("", encoding="utf-8")
        self.env = {
            **os.environ,
            "WORK_DIR": str(self.work),
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": str(self.home / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        self.env.pop("CLAUDE_PROJECT_DIR", None)
        self.git(self.work, "init", "-q")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- fixtures -------------------------------------------------------------------------------------------

    def git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=self.env)

    def write_json(self, relative: str, value: object, indent: int | None = 2) -> Path:
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=indent) + "\n", encoding="utf-8")
        return path

    def read_json(self, relative: str) -> object:
        return json.loads((self.work / relative).read_text(encoding="utf-8"))

    def make_brain(self, name: str) -> Path:
        """A blank brain as the seed leaves it: empty boundary, no owner, its own Git repository."""
        brain = self.work / name
        (brain / ".data").mkdir(parents=True)
        (brain / "AGENTS.md").write_text(f"# {name}\n", encoding="utf-8")
        self.write_json(f"{name}/.data/brain.json", EMPTY_BOUNDARY)
        self.write_json(f"{name}/.data/doctor.json", {"owner": ""})
        self.git(brain, "init", "-q")
        return brain

    def two_brains(self) -> None:
        self.make_brain("brain-acme")
        self.make_brain("brain-perso")

    def complete(self) -> None:
        """Every setting answered and every owner check satisfied."""
        self.two_brains()
        self.write_json("work-config.local.json", {"version": 1, "defaultBrain": "brain-acme", "artifactsDir": "artifacts"})
        (self.work / "artifacts").mkdir()
        (self.home / "inbox/transcripts").mkdir(parents=True)
        self.write_json("brain-acme/.data/local-paths.json", {"_note": "x", "transcripts_dir": "inbox/transcripts", "recordings_dir": "", "brains": ["brain-acme", "brain-perso"]})
        for name, scope in (("brain-acme", "employer"), ("brain-perso", "personal")):
            boundary = {**EMPTY_BOUNDARY, "scope": scope, "description": f"{scope} notes", "remote": "git@git.acme.example:acme/*", "email": "*@acme.example"}
            self.write_json(f"{name}/.data/brain.json", boundary)
            self.write_json(f"{name}/.data/doctor.json", {"owner": "Jane Doe"})
        for repo in (self.work, self.work / "brain-acme", self.work / "brain-perso"):
            self.git(repo, "config", "user.email", "jane@acme.example")
            for hook in ("pre-commit", "commit-msg", "pre-push"):
                (repo / ".git/hooks" / hook).write_text("#!/bin/sh\n", encoding="utf-8")
        (self.work / ".work-state.json").write_text('{"configHash": "x"}\n', encoding="utf-8")
        (self.work / ".obsidian").mkdir()

    # --- runners --------------------------------------------------------------------------------------------

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True, timeout=60)

    def ok(self, *args: str) -> str:
        result = self.run_tool(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def refused(self, *args: str) -> str:
        result = self.run_tool(*args)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result.stderr

    def status(self) -> tuple[int, dict]:
        result = self.run_tool("status", "--json")
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def items(self) -> dict[str, dict]:
        return {item["key"]: item for item in self.status()[1]["items"]}

    def missing(self) -> list[str]:
        return [key for key, item in self.items().items() if item["state"] == "missing"]


class StatusTest(SetupTestCase):
    def test_blank_workspace_lists_every_setting_as_missing(self) -> None:
        self.two_brains()
        code, report = self.status()
        self.assertEqual(code, 1)
        self.assertFalse(report["complete"])
        brain_keys = [f"{name}.{field}" for name in ("brain-acme", "brain-perso") for field in BRAIN_SETTINGS]
        self.assertEqual(self.missing(), ["defaultBrain", "artifactsDir", "brains", "transcripts_dir", *brain_keys])
        items = self.items()
        self.assertIsNone(items["defaultBrain"]["default"])
        self.assertEqual(items["defaultBrain"]["suggestion"], "brain-acme")
        self.assertIn("several brains", items["defaultBrain"]["detail"])
        self.assertEqual(items["artifactsDir"]["default"], "artifacts")
        self.assertEqual(items["artifactsDir"]["where"], "work-config.local.json")
        self.assertEqual(items["transcripts_dir"]["default"], TRANSCRIPTS_DEFAULT)
        self.assertEqual(items["transcripts_dir"]["detail"], "answer defaultBrain first")
        self.assertEqual(items["brain-perso.scope"]["default"], "personal")
        self.assertIsNone(items["brain-acme.scope"]["default"])
        self.assertEqual(items["brain-acme.scope"]["suggestion"], "employer")
        self.assertIn("nothing from work", items["brain-perso.description"]["default"])
        self.assertEqual(items["brain-acme.owner"]["where"], "brain-acme/.data/doctor.json")
        self.assertEqual(items["brain-acme.email"]["where"], "brain-acme/.data/brain.json")
        for item in items.values():
            if item["state"] == "missing":
                self.assertTrue(item["question"].endswith("?"), item)
        self.assertEqual(items["obsidian"]["state"], "owner-action")
        self.assertEqual(items["git-identity"]["state"], "owner-action")
        self.assertIn("Work: no commit e-mail", items["git-identity"]["detail"])
        text = self.run_tool("status").stdout
        self.assertIn("Setup: 14 missing", text)
        self.assertIn("question: Which brain should the tools use", text)
        self.assertIn("setup.py set <key> <value>", text)

    def test_a_single_brain_is_the_default_brain_by_rule(self) -> None:
        self.make_brain("brain-acme")
        items = self.items()
        self.assertEqual(items["defaultBrain"]["state"], "done")
        self.assertEqual(items["brains"]["where"], "brain-acme/.data/local-paths.json")
        self.assertEqual(items["brains"]["default"], "brain-acme")

    def test_complete_workspace(self) -> None:
        self.complete()
        code, report = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(report["complete"])
        self.assertEqual({item["key"]: item["state"] for item in report["items"] if item["state"] != "done"}, {})
        self.assertIn("Setup: 0 missing, 0 to do by the owner", self.ok("status"))

    def test_status_prints_no_configured_value(self) -> None:
        self.complete()
        self.git(self.work / "brain-acme", "remote", "add", "origin", "git@git.acme.example:acme/brain-acme.git")
        out = self.ok("status") + self.ok("status", "--json")
        for value in ("Jane Doe", "inbox/transcripts", "jane@acme.example", "acme/brain-acme.git", "employer notes"):
            self.assertNotIn(value, out)

    def test_unreadable_file_stops_status_and_writes(self) -> None:
        self.complete()
        (self.work / "brain-perso/.data/doctor.json").write_text("{ not json", encoding="utf-8")
        result = self.run_tool("status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read brain-perso/.data/doctor.json", result.stderr)
        self.assertIn("cannot read", self.refused("set", "brain-acme.owner", "Jane Doe"))


class SetTest(SetupTestCase):
    def test_default_brain_goes_to_the_local_layer(self) -> None:
        self.two_brains()
        out = self.ok("set", "defaultBrain", "brain-perso")
        self.assertIn("defaultBrain: written to work-config.local.json", out)
        self.assertEqual(self.read_json("work-config.local.json"), {"version": 1, "defaultBrain": "brain-perso"})
        result = subprocess.run([sys.executable, str(WORK_CONFIG), "default-brain"], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "brain-perso")
        self.assertNotIn("defaultBrain", self.missing())
        self.assertEqual(self.items()["transcripts_dir"]["where"], "brain-perso/.data/local-paths.json")

    def test_default_brain_is_validated_like_work_config(self) -> None:
        self.two_brains()
        self.write_json("work-config.local.json", {"version": 1, "skills": {"disabled": ["x-skill"]}})
        before = (self.work / "work-config.local.json").read_text(encoding="utf-8")
        self.assertIn("invalid brain name", self.refused("set", "defaultBrain", "Brain_Acme"))
        self.assertIn("not a brain at the Work root", self.refused("set", "defaultBrain", "brain-globex"))
        self.assertEqual((self.work / "work-config.local.json").read_text(encoding="utf-8"), before)
        self.ok("set", "defaultBrain", "brain-acme")
        self.assertEqual(self.read_json("work-config.local.json"), {"version": 1, "skills": {"disabled": ["x-skill"]}, "defaultBrain": "brain-acme"})

    def test_artifacts_dir_inside_is_created_outside_must_exist(self) -> None:
        self.make_brain("brain-acme")
        self.ok("set", "artifactsDir", "artifacts")
        self.assertTrue((self.work / "artifacts").is_dir())
        synced = self.home / "globex-sync/artifacts"
        error = self.refused("set", "artifactsDir", str(synced))
        self.assertIn("does not exist", error)
        self.assertEqual(self.read_json("work-config.local.json")["artifactsDir"], "artifacts")
        synced.mkdir(parents=True)
        out = self.ok("set", "artifactsDir", "~/globex-sync/artifacts")
        self.assertIn("bootstrap.sh", out)
        self.assertEqual(self.read_json("work-config.local.json")["artifactsDir"], "~/globex-sync/artifacts")
        check = subprocess.run([sys.executable, str(WORK_CONFIG), "check"], env=self.env, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(self.items()["artifacts-link"]["state"], "owner-action")
        self.assertIn("artifacts/ is a real folder", self.items()["artifacts-link"]["detail"])

    def test_each_setting_is_written_where_it_belongs(self) -> None:
        self.two_brains()
        self.ok("set", "defaultBrain", "brain-acme")
        perso_before = {name: (self.work / "brain-perso/.data" / name).read_text(encoding="utf-8") for name in ("brain.json", "doctor.json")}
        (self.work / "brain-acme/.data/doctor.json").unlink()
        self.ok("set", "brain-acme.owner", "Jane", "Doe")
        self.assertEqual(self.read_json("brain-acme/.data/doctor.json"), {"owner": "Jane Doe"})
        self.ok("set", "brain-acme.scope", "Employer")
        self.ok("set", "brain-acme.description", "Work for Acme and its clients; nothing personal.")
        self.ok("set", "brain-acme.remote", "git@git.acme.example:acme/*")
        self.ok("set", "brain-acme.email", "*@acme.example")
        self.assertEqual(self.read_json("brain-acme/.data/brain.json"), {
            "allow": [], "description": "Work for Acme and its clients; nothing personal.", "email": "*@acme.example",
            "remote": "git@git.acme.example:acme/*", "scope": "employer", "version": 1,
        })
        self.ok("set", "brains", "brain-acme, brain-perso")
        self.ok("set", "transcripts_dir", str(self.home / "inbox/transcripts"))
        self.assertEqual(self.read_json("brain-acme/.data/local-paths.json"), {"brains": ["brain-acme", "brain-perso"], "transcripts_dir": "inbox/transcripts"})
        self.assertFalse((self.work / "brain-perso/.data/local-paths.json").exists())
        for name, text in perso_before.items():
            self.assertEqual((self.work / "brain-perso/.data" / name).read_text(encoding="utf-8"), text)
        self.assertEqual([key for key in self.missing() if key.startswith("brain-acme.")], [])

    def test_writes_keep_layout_order_and_other_keys(self) -> None:
        self.make_brain("brain-acme")
        paths = {"_note": "Input folders.", "transcripts_dir": "", "recordings_dir": "", "brains": ["brain-acme"]}
        (self.work / "brain-acme/.data/local-paths.json").write_text(json.dumps(paths, indent=4), encoding="utf-8")  # no final newline
        self.write_json("brain-acme/.data/brain.json", {**EMPTY_BOUNDARY, "allow": ["globex"], "scope": "employer"})
        self.ok("set", "transcripts_dir", "~/inbox/transcripts")
        self.ok("set", "brain-acme.remote", "git@git.acme.example:acme/*")
        text = (self.work / "brain-acme/.data/local-paths.json").read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps({**paths, "transcripts_dir": "inbox/transcripts"}, indent=4))
        text = (self.work / "brain-acme/.data/brain.json").read_text(encoding="utf-8")
        expected = {**EMPTY_BOUNDARY, "allow": ["globex"], "scope": "employer", "remote": "git@git.acme.example:acme/*"}
        self.assertEqual(text, json.dumps(expected, indent=2, sort_keys=True) + "\n")
        self.assertEqual(sorted(path.name for path in (self.work / "brain-acme/.data").iterdir()), ["brain.json", "doctor.json", "local-paths.json"])

    def test_answers_are_validated(self) -> None:
        self.two_brains()
        self.ok("set", "defaultBrain", "brain-acme")
        refusals = (
            ("brain-acme.scope", "Employer!", "lowercase label"),
            ("brain-acme.remote", "https://jane:secret@git.acme.example/acme.git", "password"),  # secret-scan: ignore (refused on purpose)
            ("brain-acme.remote", "two words", "without spaces"),
            ("brain-acme.email", "jane.acme.example", "e-mail pattern"),
            ("brain-acme.owner", " ", "empty answer"),
            ("brain-acme.description", "x" * 501, "500 characters"),
            ("transcripts_dir", "/elsewhere/transcripts", "under your home folder"),
            ("transcripts_dir", "../outside", "under your home folder"),
            ("transcripts_dir", str(self.work / "inbox"), "outside the workspace"),
            ("brains", "brain-perso", "must include the default brain"),
            ("brains", "brain-acme, Brain_X", "invalid brain name"),
            ("artifactsDir", " ", "non-empty path"),
            ("nonsense", "x", "unknown setting"),
            ("obsidian", "yes", "done by the owner"),
        )
        snapshot = {path: path.read_bytes() for path in self.work.rglob("*.json") if ".git" not in path.parts}
        for key, value, message in refusals:
            with self.subTest(key=key, value=value):
                self.assertIn(message, self.refused("set", key, value))
        self.assertEqual({path: path.read_bytes() for path in self.work.rglob("*.json") if ".git" not in path.parts}, snapshot)

    def test_local_paths_need_a_default_brain(self) -> None:
        self.two_brains()
        self.assertIn("answer defaultBrain first", self.refused("set", "transcripts_dir", "inbox/transcripts"))
        self.assertIn("answer defaultBrain first", self.refused("default", "brains"))


class DefaultTest(SetupTestCase):
    def test_default_and_ignore_write_the_default(self) -> None:
        self.two_brains()
        acme = self.work / "brain-acme"
        self.git(acme, "remote", "add", "origin", "git@git.acme.example:acme/brain-acme.git")
        self.git(acme, "config", "user.email", "jane@acme.example")
        self.git(acme, "config", "user.name", "Jane Doe")
        self.ok("set", "defaultBrain", "brain-acme")
        self.ok("default", "artifactsDir")
        self.assertEqual(self.read_json("work-config.local.json")["artifactsDir"], "artifacts")
        self.assertTrue((self.work / "artifacts").is_dir())
        self.ok("ignore", "transcripts_dir")
        self.ok("default", "brains")
        self.assertEqual(self.read_json("brain-acme/.data/local-paths.json"), {"transcripts_dir": TRANSCRIPTS_DEFAULT, "brains": ["brain-acme", "brain-perso"]})
        self.ok("default", "brain-acme.remote")
        self.ok("ignore", "brain-acme.email")
        self.ok("default", "brain-acme.owner")
        self.ok("ignore", "brain-perso.owner")  # the owner of the default brain
        self.ok("default", "brain-perso.scope")
        self.ok("default", "brain-perso.description")
        acme_boundary = self.read_json("brain-acme/.data/brain.json")
        self.assertEqual((acme_boundary["remote"], acme_boundary["email"]), ("git@git.acme.example:acme/brain-acme.git", "jane@acme.example"))
        self.assertEqual(self.read_json("brain-perso/.data/doctor.json"), {"owner": "Jane Doe"})
        perso = self.read_json("brain-perso/.data/brain.json")
        self.assertEqual(perso["scope"], "personal")
        self.assertIn("nothing from work", perso["description"])
        self.assertEqual(self.missing(), ["brain-acme.scope", "brain-acme.description", "brain-perso.remote", "brain-perso.email"])
        self.assertEqual(self.items()["transcripts-folder"]["state"] if "transcripts-folder" in self.items() else "absent", "absent")

    def test_a_setting_without_default_cannot_be_skipped(self) -> None:
        self.two_brains()
        self.assertIn("no sensible default", error := self.refused("default", "defaultBrain"))
        self.assertIn("suggestion: brain-acme", error)
        self.ok("set", "defaultBrain", "brain-acme")
        self.assertIn("suggestion: employer", self.refused("ignore", "brain-acme.scope"))
        self.assertIn("suggestion: git@<host>", self.refused("default", "brain-acme.remote"))
        self.assertIn("suggestion: *@", self.refused("default", "brain-acme.email"))
        self.assertIn("first and last name", self.refused("default", "brain-acme.owner"))
        self.assertEqual(self.read_json("brain-acme/.data/brain.json"), EMPTY_BOUNDARY)

    def test_default_of_a_done_setting_writes_nothing(self) -> None:
        self.make_brain("brain-acme")
        (self.home / "globex-sync").mkdir()
        self.ok("set", "artifactsDir", str(self.home / "globex-sync"))
        self.assertIn("already set; nothing written", self.ok("default", "artifactsDir"))
        self.assertEqual(self.read_json("work-config.local.json")["artifactsDir"], str(self.home / "globex-sync"))


class OwnerActionTest(SetupTestCase):
    def test_owner_actions_never_block(self) -> None:
        self.complete()
        shutil.rmtree(self.work / ".obsidian")
        self.git(self.work / "brain-perso", "config", "user.email", "jane@globex.example")
        code, report = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(report["complete"])
        items = self.items()
        self.assertEqual(items["obsidian"]["state"], "owner-action")
        self.assertIn("kit/obsidian/README.md", items["obsidian"]["instruction"])
        self.assertEqual(items["git-identity"]["detail"], "brain-perso: commit e-mail outside the email pattern of its brain.json")
        self.assertIn("GIT-IDENTITY.md", items["git-identity"]["instruction"])
        self.assertIn("done by the owner", self.refused("set", "git-identity", "x"))

    def test_bootstrap_expected_brains_and_transcripts_folder(self) -> None:
        self.complete()
        (self.work / "brain-perso/.git/hooks/pre-push").unlink()
        (self.work / ".work-state.json").unlink()
        self.write_json("brain-acme/.data/local-paths.json", {"transcripts_dir": "inbox/elsewhere", "brains": ["brain-acme", "brain-perso", "brain-globex"]})
        items = self.items()
        self.assertEqual(items["bootstrap"]["detail"], "Git hooks missing in brain-perso; no .work-state.json")
        self.assertIn("brain-globex", items["expected-brains"]["instruction"])
        self.assertEqual(items["transcripts-folder"]["state"], "owner-action")
        self.assertEqual(self.missing(), [])

    def test_tools_env_is_checked_for_the_skills_that_read_it(self) -> None:
        self.complete()
        skill = self.work / "brain-acme/skills/acme-sheet"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# acme-sheet\n\nThe tokens go in `tools/.env` at the Work root.\n", encoding="utf-8")
        other = self.work / "brain-acme/skills/acme-notes"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("# acme-notes\n\nNames only in `tools/.env.example`.\n", encoding="utf-8")
        item = self.items()["tools-env"]
        self.assertEqual(item["state"], "owner-action")
        self.assertIn("acme-sheet", item["instruction"])
        self.assertNotIn("acme-notes", item["instruction"])
        (self.work / "tools").mkdir(exist_ok=True)
        (self.work / "tools/.env").write_text("", encoding="utf-8")
        self.assertEqual(self.items()["tools-env"]["state"], "done")


class HookBlockTest(SetupTestCase):
    def setUp(self) -> None:
        super().setUp()
        machine = self.work / "tools/machine"
        machine.mkdir(parents=True)
        for source in (WORK_CONFIG, TOOL):
            shutil.copy(source, machine / source.name)

    def run_hook(self) -> str:
        env = {**self.env, "CLAUDE_PROJECT_DIR": str(self.work)}
        result = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("Workspace:", result.stdout)
        return result.stdout

    def test_block_when_incomplete(self) -> None:
        self.two_brains()
        out = self.run_hook()
        state, _, block = out.partition("\nSetup incomplete")
        self.assertIn("brain-state.py map", state)
        self.assertIn("before any other work in this conversation", block)
        self.assertIn("one question at a time, in the user's language", block)
        self.assertIn("`uv run tools/machine/setup.py set <key> <value>`", block)
        self.assertIn("`uv run tools/machine/setup.py default <key>`", block)
        self.assertIn("- `defaultBrain`: Which brain should the tools use when none is named (brain-acme, brain-perso)?", block)
        self.assertIn("No default (suggest: brain-acme).", block)
        self.assertIn("- `artifactsDir`:", block)
        self.assertIn("Default: artifacts.", block)
        self.assertIn("- `brain-perso.scope`: What is the scope of brain-perso: personal, employer or client? Default: personal.", block)
        self.assertIn("To do by the owner, not blocking (mention it once, briefly): ", block)
        self.assertEqual(block.count("To do by the owner"), 1)
        self.assertIn("`git-identity`", block)
        self.assertIn("Default: Personal notes, projects, contacts and career; nothing from work for an employer or a client.\n", block)
        self.assertNotIn("more: `uv run tools/machine/setup.py status`", block)
        self.assertLessEqual(len(block.split()), 505)

    def test_long_list_is_cut_but_keeps_the_owner_actions(self) -> None:
        for name in ("brain-acme", "brain-acme-lab", "brain-globex", "brain-initech", "brain-perso"):
            self.make_brain(name)
        block = self.run_hook().partition("\nSetup incomplete")[2]
        self.assertIn("- more: `uv run tools/machine/setup.py status`", block)
        self.assertTrue(block.rstrip().splitlines()[-1].startswith("To do by the owner, not blocking"))
        self.assertLessEqual(len(block.split()), 505)

    def test_owner_actions_alone_do_not_ask_anything(self) -> None:
        self.complete()
        shutil.rmtree(self.work / ".obsidian")
        out = self.run_hook()
        self.assertNotIn("Setup incomplete", out)
        self.assertIn("Setup: to do by the owner, not blocking", out)
        self.assertIn("`obsidian`", out)

    def test_nothing_about_setup_when_complete(self) -> None:
        self.complete()
        out = self.run_hook()
        self.assertNotIn("Setup", out)
        self.assertNotIn("setup.py", out)

    def test_unreadable_file_prints_nothing_about_setup(self) -> None:
        self.two_brains()
        doctor = self.work / "brain-acme/.data/doctor.json"
        doctor.write_text("{ not json", encoding="utf-8")
        self.assertNotIn("Setup", self.run_hook())
        if os.name == "posix" and os.geteuid() != 0:
            doctor.write_text('{"owner": ""}', encoding="utf-8")
            doctor.chmod(0)
            try:
                self.assertNotIn("Setup", self.run_hook())
            finally:
                doctor.chmod(0o644)
        (self.work / "work-config.local.json").write_text("{", encoding="utf-8")
        self.assertNotIn("Setup", self.run_hook())


if __name__ == "__main__":
    unittest.main()
