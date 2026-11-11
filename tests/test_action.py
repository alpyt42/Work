"""Regression checks for the closed-action archiver (no network, no real brain)."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "tools/brain/action.py"
HEADER = (
    "# Actions archive 2026 — Alpha\n\n"
    "> Closed actions of Alpha archived for 2026; the live register is [actions.md](actions.md). IDs stay reserved.\n\n"
    "## Done\n"
)

ALPHA = """# Actions — Alpha

> Registre de test.

## Open
- [ ] **AAA-001** — Jane — Encore ouverte
    - due: 2026-12-01
- [x] **AAA-002** — Jane — Cochée hier, rangée plus tard ✅ 2026-10-11

## Done
- [x] **AAA-010** — Jane — Récente ✅ 2026-10-05
    - source: [x](../sources/x.md)
- [x] **AAA-011** — Jane — Ancienne avec détails ✅ 2026-08-15
    - source: [x](../sources/x.md)
    - 15/08: fait
        - enfant à huit espaces

    - 16/08: après une ligne blanche interne
- [x] **AAA-012** — Jane — Sans date de clôture
    - 10/08: fait sans ✅
- [x] **AAA-013** — Jane — Plus ancienne encore ✅ 2026-07-01

## Cancelled
- [-] **AAA-020** — Jane — Abandonnée tôt ✅ 2026-06-01
    - 01/06: stop
- [-] **AAA-021** — Jane — Abandonnée récemment ❌ 2026-10-01
"""

ALPHA_AFTER = """# Actions — Alpha

> Registre de test.

## Open
- [ ] **AAA-001** — Jane — Encore ouverte
    - due: 2026-12-01
- [x] **AAA-002** — Jane — Cochée hier, rangée plus tard ✅ 2026-10-11

## Done
- [x] **AAA-010** — Jane — Récente ✅ 2026-10-05
    - source: [x](../sources/x.md)
- [x] **AAA-012** — Jane — Sans date de clôture
    - 10/08: fait sans ✅

## Cancelled
- [-] **AAA-021** — Jane — Abandonnée récemment ❌ 2026-10-01
"""

BETA = """# Actions — Beta

## Open

## Done
- [x] **BBB-001** — Jane — Clôturée l'an dernier ✅ 2025-12-20
- [x] **BBB-002** — Jane — Clôturée cette année ✅ 2026-02-03
    - note

## Cancelled
"""


class ArchiveActionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name).resolve() / "Work"
        self.brain = self.work / "brain"
        self.alpha = self.brain / "projects/clients/acme/missions/alpha/state"
        self.beta = self.brain / "projects/internal/beta/state"
        for folder, content in ((self.alpha, ALPHA), (self.beta, BETA)):
            folder.mkdir(parents=True)
            (folder / "actions.md").write_text(content, encoding="utf-8")
        self.env = {**os.environ, "WORK_DIR": str(self.work)}
        self.env.pop("BRAIN_DIR", None)
        self.env.pop("ARCHIVE_TODAY", None)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_tool(self, *args: str, code: int = 0, env: dict | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(TOOL), "--brain", str(self.brain), "archive", "--today", "2026-10-12", *args],
            env=env or self.env, cwd=self.work, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def read(self, folder: Path, name: str = "actions.md") -> str:
        return (folder / name).read_text(encoding="utf-8")

    def test_check_fails_when_something_would_move_and_writes_nothing(self) -> None:
        result = self.run_tool("--check", code=1)
        self.assertIn("Misfiled actions", result.stdout)
        self.assertEqual(self.read(self.alpha), ALPHA)

    def test_check_with_register_filter_and_clean_register(self) -> None:
        clean = self.beta / "actions.md"
        self.run_tool("--check", "--register", str(clean), "--days", "100000")
        self.run_tool("--check", "--register", str(self.alpha / "actions.md"), code=1)

    def test_dry_run_reports_without_writing(self) -> None:
        out = self.run_tool().stdout
        self.assertIn("brain/projects/clients/acme/missions/alpha/state/actions.md: archive 3 action(s) → actions-archive-2026.md (AAA-011, AAA-013, AAA-020)", out)
        self.assertIn("brain/projects/internal/beta/state/actions.md: archive 2 action(s) → actions-archive-2025.md (BBB-001) ; actions-archive-2026.md (BBB-002)", out)
        self.assertIn("Total archive: 5 action(s) to move in 2 register(s)", out)
        self.assertEqual(self.read(self.alpha), ALPHA)
        self.assertEqual(self.read(self.beta), BETA)
        self.assertEqual(sorted(p.name for p in self.alpha.iterdir()), ["actions.md"])

    def test_quiet_prints_only_total(self) -> None:
        out = self.run_tool("--quiet").stdout.strip().splitlines()
        self.assertEqual(len(out), 2)  # total + dry-run hint
        self.assertTrue(out[0].startswith("Total archive: 5 action(s)"))

    def test_write_moves_only_old_dated_closed_actions_with_children(self) -> None:
        out = self.run_tool("--write").stdout
        self.assertIn("3 action(s) moved →", out)
        self.assertEqual(self.read(self.alpha), ALPHA_AFTER)
        archive = self.read(self.alpha, "actions-archive-2026.md")
        self.assertEqual(
            archive,
            HEADER
            + "- [x] **AAA-011** — Jane — Ancienne avec détails ✅ 2026-08-15\n"
            "    - source: [x](../sources/x.md)\n"
            "    - 15/08: fait\n"
            "        - enfant à huit espaces\n\n"
            "    - 16/08: après une ligne blanche interne\n"
            "- [x] **AAA-013** — Jane — Plus ancienne encore ✅ 2026-07-01\n\n"
            "## Cancelled\n"
            "- [-] **AAA-020** — Jane — Abandonnée tôt ✅ 2026-06-01\n"
            "    - 01/06: stop\n",
        )

    def test_year_split_creates_one_archive_per_closure_year(self) -> None:
        self.run_tool("--write")
        self.assertEqual(sorted(p.name for p in self.beta.iterdir()), ["actions-archive-2025.md", "actions-archive-2026.md", "actions.md"])
        self.assertIn("- [x] **BBB-001**", self.read(self.beta, "actions-archive-2025.md"))
        self.assertNotIn("BBB-002", self.read(self.beta, "actions-archive-2025.md"))
        self.assertIn("    - note\n", self.read(self.beta, "actions-archive-2026.md"))
        self.assertIn("# Actions archive 2025 — Beta", self.read(self.beta, "actions-archive-2025.md"))
        self.assertEqual(self.read(self.beta), "# Actions — Beta\n\n## Open\n\n## Done\n\n## Cancelled\n")

    def test_appends_to_existing_archive_sorted_newest_first(self) -> None:
        existing = (
            HEADER
            + "- [x] **AAA-090** — Jane — Très récente ✅ 2026-09-01\n"
            "- [x] **AAA-091** — Jane — Même jour que la nouvelle ✅ 2026-08-15\n"
            "    - ancien\n"
            "- [x] **AAA-092** — Jane — Plus vieille ✅ 2026-03-01\n\n"
            "## Cancelled\n"
            "- [-] **AAA-093** — Jane — Annulée avant ❌ 2026-01-10\n"
        )
        (self.alpha / "actions-archive-2026.md").write_text(existing, encoding="utf-8")
        self.run_tool("--write")
        archive = self.read(self.alpha, "actions-archive-2026.md")
        order = [line.split("**")[1] for line in archive.splitlines() if line.startswith("- [")]
        self.assertEqual(order, ["AAA-090", "AAA-091", "AAA-011", "AAA-013", "AAA-092", "AAA-020", "AAA-093"])
        self.assertEqual(archive.count("## Done"), 1)
        self.assertIn("\n\n## Cancelled\n", archive)
        self.assertNotIn("\n\n\n", archive)

    def test_closed_action_outside_closed_sections_warns_and_stays(self) -> None:
        text = ALPHA.replace("- [ ] **AAA-001** — Jane — Encore ouverte", "- [x] **AAA-001** — Jane — Mal rangée ✅ 2026-05-01")
        (self.alpha / "actions.md").write_text(text, encoding="utf-8")
        out = self.run_tool("--write").stdout
        self.assertIn("WARNING", out)
        self.assertIn("AAA-001", out.split("WARNING", 1)[1])
        self.assertIn("- [x] **AAA-001** — Jane — Mal rangée", self.read(self.alpha))
        self.assertNotIn("AAA-001", self.read(self.alpha, "actions-archive-2026.md"))

    def test_duplicate_id_in_archive_is_an_error_and_changes_nothing(self) -> None:
        archive = HEADER + "- [x] **AAA-013** — Jane — Déjà là ✅ 2026-07-01\n\n## Cancelled\n"
        (self.alpha / "actions-archive-2026.md").write_text(archive, encoding="utf-8")
        result = self.run_tool("--write", code=1)
        self.assertIn("AAA-013", result.stderr)
        self.assertEqual(self.read(self.alpha), ALPHA)
        self.assertEqual(self.read(self.alpha, "actions-archive-2026.md"), archive)
        # The other register is processed independently.
        self.assertEqual(self.read(self.beta), "# Actions — Beta\n\n## Open\n\n## Done\n\n## Cancelled\n")

    def test_second_write_moves_nothing(self) -> None:
        self.run_tool("--write")
        snapshot = {p: p.read_bytes() for p in self.brain.rglob("*.md")}
        out = self.run_tool("--write").stdout
        self.assertIn("Total archive: 0 action(s) moved", out)
        self.assertEqual(snapshot, {p: p.read_bytes() for p in self.brain.rglob("*.md")})

    def test_crlf_register_is_preserved(self) -> None:
        crlf = ALPHA.replace("\n", "\r\n").encode("utf-8")
        (self.alpha / "actions.md").write_bytes(crlf)
        self.run_tool("--write")
        self.assertEqual((self.alpha / "actions.md").read_bytes(), ALPHA_AFTER.replace("\n", "\r\n").encode("utf-8"))
        archive = (self.alpha / "actions-archive-2026.md").read_bytes()
        self.assertEqual(archive.count(b"\r\n"), archive.count(b"\n"))

    def test_register_without_trailing_newline_keeps_none(self) -> None:
        (self.alpha / "actions.md").write_text(ALPHA_AFTER.rstrip("\n") + "\n- [x] **AAA-030** — Jane — Dernière ✅ 2026-01-01", encoding="utf-8")
        self.run_tool("--write")
        text = self.read(self.alpha)
        self.assertFalse(text.endswith("\n"))
        self.assertNotIn("AAA-030", text)
        self.assertTrue(text.rstrip().endswith("❌ 2026-10-01"))

    def test_days_and_today_change_the_cutoff(self) -> None:
        # --days 90 from 2026-10-12: cutoff 2026-07-14, so AAA-011 (2026-08-15) stays.
        out = self.run_tool("--days", "90").stdout
        self.assertIn("Total archive: 4 action(s)", out)
        self.assertNotIn("AAA-011", out)
        # An earlier "today": cutoff 2026-07-21, AAA-011 still too recent.
        out = self.run_tool("--today", "2026-08-20").stdout
        self.assertIn("Total archive: 4 action(s)", out)
        self.assertNotIn("AAA-011", out)

    def test_cutoff_is_strict(self) -> None:
        # Closure 2026-08-15 with today 2026-09-14 and 30 days: exactly on the cutoff, kept.
        out = self.run_tool("--today", "2026-09-14").stdout
        self.assertNotIn("AAA-011", out)
        out = self.run_tool("--today", "2026-09-15").stdout
        self.assertIn("AAA-011", out)

    def test_env_override_for_today(self) -> None:
        env = {**self.env, "ARCHIVE_TODAY": "2026-09-14"}
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), "archive", "--quiet"], env=env, cwd=self.work, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Total archive: 4 action(s)", result.stdout)  # cutoff 2026-08-15: AAA-011 (same day) stays

    def test_symlinked_register_is_ignored(self) -> None:
        outside = Path(self._tmp.name).resolve() / "outside"
        (outside / "state").mkdir(parents=True)
        (outside / "state/actions.md").write_text(BETA, encoding="utf-8")
        link = self.brain / "projects/internal/linked"
        link.symlink_to(outside, target_is_directory=True)
        out = self.run_tool("--write").stdout
        self.assertNotIn("linked", out)
        self.assertEqual((outside / "state/actions.md").read_text(encoding="utf-8"), BETA)

    def test_failed_register_write_restores_archives(self) -> None:
        archive = HEADER + "- [x] **AAA-090** — Jane — Déjà archivée ✅ 2026-09-01\n\n## Cancelled\n"
        (self.alpha / "actions-archive-2026.md").write_text(archive, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("archive_actions", TOOL)
        module = importlib.util.module_from_spec(spec)
        sys.modules["archive_actions"] = module
        self.addCleanup(sys.modules.pop, "archive_actions", None)
        spec.loader.exec_module(module)
        plan = module.plan_register(self.alpha / "actions.md", date(2026, 10, 12), 30)
        real = module.atomic_write_text

        def flaky(path: Path, text: str) -> None:
            if path.name == "actions.md":
                raise OSError("disque plein")
            real(path, text)

        with patch.object(module, "atomic_write_text", flaky), self.assertRaises(OSError):
            module.apply_plan(plan)
        self.assertEqual(self.read(self.alpha, "actions-archive-2026.md"), archive)
        self.assertEqual(self.read(self.alpha), ALPHA)
        self.assertEqual(sorted(p.name for p in self.alpha.iterdir()), ["actions-archive-2026.md", "actions.md"])



class ActionCommandTest(unittest.TestCase):
    """create / update / history / delete / list / show, as the agents and tasks-web run them."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.folder = self.brain / "projects/clients/acme/missions/gamma"
        (self.folder / "state").mkdir(parents=True)
        (self.folder / "sources").mkdir()
        (self.folder / "sources/cr.md").write_text("Ancienne mention GAM-007\n", encoding="utf-8")
        self.register = self.folder / "state/actions.md"
        self.register.write_text(REGISTER, encoding="utf-8")
        self.env = {**os.environ, "ACTION_NOW": "2026-10-13 14:32"}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def act(self, *args: str, code: int = 0, now: str | None = None) -> dict | list:
        env = {**self.env, **({"ACTION_NOW": now} if now else {})}
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), *args], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        try:
            return json.loads(result.stdout)
        except ValueError:
            return result.stdout

    def text(self) -> str:
        return self.register.read_text(encoding="utf-8")

    def create(self, **extra: str) -> dict:
        args = ["create", "--project", "acme/gamma", "--title", "Préparer la démo", "--owner", "Owner", "--source", "[CR](../sources/cr.md)"]
        for key, value in extra.items():
            args += [f"--{key.replace('_', '-')}={value}"]
        return self.act(*args)

    def test_create_allocates_next_id_of_client_folder_and_writes_stamps(self) -> None:
        result = self.create(priority="high", due="2026-10-14", due_note="avant l'atelier")
        self.assertEqual((result["id"], result["created_at"], result["label"]), ("GAM-008", "2026-10-13 14:32", "creation of GAM-008"))
        self.assertIn(
            "    - source: s\n"
            "- [ ] **GAM-008** — Owner — Préparer la démo ⏫ ➕ 2026-10-13 📅 2026-10-14\n"
            "    - due: avant l'atelier\n"
            "    - source: [CR](../sources/cr.md)\n"
            "    - created: 2026-10-13 14:32\n"
            "    - updated: 2026-10-13 14:32\n\n## Done", self.text())
        shown = self.act("show", "GAM-008")
        self.assertEqual((shown["created_at"], shown["updated_at"], shown["due"]), ("2026-10-13 14:32", "2026-10-13 14:32", "2026-10-14"))
        self.assertEqual([note["deletable"] for note in shown["notes"]], [True, False, False, False])

    def test_show_finds_an_archived_action_and_writes_still_refuse_it(self) -> None:
        self.act("update", "GAM-001", "--state", "x", "--closed-on", "2026-01-05")
        self.act("archive", "--write", "--today", "2026-10-13")
        self.assertNotIn("GAM-001", self.text())
        shown = self.act("show", "GAM-001")
        self.assertEqual((shown["state"], shown["done"], shown["archived"]), ("x", "2026-01-05", True))
        self.assertEqual(shown["register"], "projects/clients/acme/missions/gamma/state/actions-archive-2026.md")
        self.assertIn("- source: s", shown["details"])
        self.assertNotIn("archived", self.act("show", self.create()["id"]))  # a live action carries no flag
        for write in (("update", "GAM-001", "--title", "x"), ("history", "add", "GAM-001", "--text", "note"), ("delete", "GAM-001")):
            self.assertEqual(self.act(*write, code=3)["kind"], "not_found")
        self.assertEqual(self.act("show", "GAM-404", code=3)["kind"], "not_found")

    def test_create_in_an_empty_register_takes_the_prefix_of_its_header_then_of_its_archives(self) -> None:
        for name, header in (("delta", "> Reserved prefix: `DEL`.\n\n"), ("epsilon", "")):
            state = self.brain / f"projects/internal/{name}/state"
            state.mkdir(parents=True)
            (state / "actions.md").write_text(f"# Actions — {name}\n\n{header}## Open\n\n## Done\n\n## Cancelled\n", encoding="utf-8")
        first = ("--title", "Première", "--owner", "Owner", "--source", "s")
        self.assertEqual(self.act("create", "--project", "delta", *first)["id"], "DEL-001")  # reserved in the header
        self.act("update", "GAM-001", "--state", "x", "--closed-on", "2026-01-05")
        self.act("archive", "--write", "--today", "2026-10-13")
        self.assertNotIn("GAM-001", self.text())
        self.assertEqual(self.create()["id"], "GAM-008")  # every action archived: the prefix of the archive
        self.assertEqual(self.act("create", "--project", "epsilon", *first, code=4)["kind"], "conflict")  # neither: still asked for
        self.assertEqual(self.act("create", "--project", "epsilon", *first, "--prefix", "EPS")["id"], "EPS-001")

    def test_project_can_be_named_several_ways(self) -> None:
        for project in ("projects/clients/acme/missions/gamma/state/actions.md", "acme / gamma", "clients/acme/missions/gamma"):
            self.act("create", "--project", project, "--title", "T", "--owner", "A", "--source", "s", "--dry-run")
        self.assertEqual(self.text(), REGISTER)
        self.assertEqual(self.act("create", "--project", "inconnu", "--title", "T", "--owner", "A", "--source", "s", code=2)["kind"], "bad_request")

    def test_validation_messages_are_english_and_the_owner_refuses_the_register_separator(self) -> None:
        base = ["create", "--project", "acme/gamma", "--title", "T", "--source", "s"]
        result = self.act(*base, "--owner", "A — B", code=2)
        self.assertEqual(result["error"], "Owner contains a separator reserved for registers.")
        result = self.act(*base, "--owner", "A", "--due", "demain", code=2)
        self.assertEqual(result["error"], "Due date must use the format YYYY-MM-DD.")
        result = self.act(*base, "--owner", "A", "--scheduled", "2026-02-30", code=2)
        self.assertEqual(result["error"], "Scheduled date is not a valid date.")
        self.assertEqual(self.act("create", "--project", "acme/gamma", "--title", "T — U", "--owner", "A", "--source", "s", "--dry-run")["id"], "GAM-008")
        self.assertEqual(self.act("update", "GAM-999", "--title", "T", code=3)["error"], "Action not found or duplicate ID.")
        self.assertEqual(self.text(), REGISTER)

    def test_update_closes_moves_stamps_and_reopen_drops_closure(self) -> None:
        self.create()
        result = self.act("update", "GAM-008", "--state", "done", now="2026-10-14 09:05")
        self.assertEqual(result["label"], "status of GAM-008 → Done")
        text = self.text()
        self.assertIn("## Done\n- [x] **GAM-008** — Owner — Préparer la démo ➕ 2026-10-13 ✅ 2026-10-14\n", text)
        self.assertIn("    - created: 2026-10-13 14:32\n    - updated: 2026-10-14 09:05\n", text)
        self.act("update", "GAM-008", "--state", "todo", now="2026-10-15 10:00")
        line = next(l for l in self.text().splitlines() if "**GAM-008**" in l)
        self.assertEqual(line, "- [ ] **GAM-008** — Owner — Préparer la démo ➕ 2026-10-13")
        self.assertLess(self.text().index("**GAM-008**"), self.text().index("## Done"))
        self.act("update", "GAM-001", "--state", "x", "--closed-on", "2026-10-10", "--due", "")
        self.assertIn("- [x] **GAM-001** — Jane — Existante ✅ 2026-10-10\n    - source: s\n    - updated: 2026-10-13 14:32", self.text())

    def test_history_add_remove_and_protected_lines(self) -> None:
        self.create()
        self.act("history", "add", "GAM-008", "--text", "slides envoyées", "--date", "2026-10-12", now="2026-10-13 16:00")
        shown = self.act("show", "GAM-008")
        self.assertEqual(shown["notes"][-1]["text"], "- 12/10: slides envoyées")
        self.assertEqual(shown["updated_at"], "2026-10-13 16:00")
        self.assertEqual(self.act("history", "remove", "GAM-008", "--index", "1", code=2)["kind"], "bad_request")
        self.assertEqual(self.act("history", "remove", "GAM-008", "--index", "3", "--expect-text", "autre", code=4)["kind"], "conflict")
        self.act("history", "remove", "GAM-008", "--index", "3", "--expect-text", "- 12/10: slides envoyées", now="2026-10-13 17:00")
        self.assertNotIn("slides envoyées", self.text())
        self.assertIn("    - updated: 2026-10-13 17:00", self.text())

    def test_versions_errors_dry_run_and_delete(self) -> None:
        version = self.act("show", "GAM-001")["version"]
        self.assertEqual(self.act("update", "GAM-001", "--title", "Autre", "--expect-version", "stale", code=4)["kind"], "conflict")
        self.assertEqual(self.act("update", "GAM-404", "--title", "x", code=3)["kind"], "not_found")
        self.assertEqual(self.act("update", "GAM-001", "--due", "2026-02-30", code=2)["kind"], "bad_request")
        self.assertEqual(self.act("update", "GAM-001", "--title", "a 📅 b", code=2)["kind"], "bad_request")
        self.act("update", "GAM-001", "--title", "Autre", "--expect-version", version, "--dry-run")
        self.assertEqual(self.text(), REGISTER)
        self.act("delete", "GAM-001")
        self.assertEqual(self.text(), "# Actions — Gamma\n\n## Open\n\n## Done\n\n## Cancelled\n")

    def test_list_filters_and_table(self) -> None:
        self.create(state="in-progress")
        self.act("update", "GAM-001", "--state", "-")
        self.assertEqual([a["id"] for a in self.act("list", "--project", "acme/gamma")], ["GAM-008"])
        self.assertEqual([a["id"] for a in self.act("list", "--state", "closed")], ["GAM-001"])
        self.assertIn("[/] GAM-008 — Owner — Préparer la démo", self.act("list", "--table"))

    def test_show_text_prints_each_piece_once_with_the_latest_history_entries(self) -> None:
        self.env["WORK_DIR"] = str(self.brain.parent.resolve())  # the brain sits in this Work root: paths are printed from it
        self.create(priority="high", due="2026-10-14", due_note="avant l'atelier", group="demo")
        for day, note in (("2026-10-10", "one"), ("2026-10-11", "two"), ("2026-10-12", "three"), ("2026-10-13", "four")):
            self.act("history", "add", "GAM-008", "--text", note, "--date", day, now="2026-10-13 16:00")
        head = ["- [ ] **GAM-008** — Owner — Préparer la démo #group/demo ⏫ ➕ 2026-10-13 📅 2026-10-14",
                "acme / gamma · due 2026-10-14 (avant l'atelier) · created 2026-10-13 14:32 · updated 2026-10-13 16:00",
                "- source: [CR](../sources/cr.md)"]
        where = "brain/projects/clients/acme/missions/gamma/state/actions.md:6"
        self.assertEqual(self.act("show", "GAM-008", "--text").splitlines(),
                         [*head, "history, last 3 of 4:", "- 11/10: two", "- 12/10: three", "- 13/10: four", where])
        self.assertEqual(self.act("show", "GAM-008", "--text", "--last", "1").splitlines(), [*head, "history, last 1 of 4:", "- 13/10: four", where])
        everything = [*head, "history, 4 entries:", "- 10/10: one", "- 11/10: two", "- 12/10: three", "- 13/10: four", where]
        self.assertEqual(self.act("show", "GAM-008", "--text", "--last", "0").splitlines(), everything)
        self.assertEqual(self.act("show", "GAM-008", "--text", "--last", "9").splitlines(), everything)
        # an action without dates or history says so, in five lines
        self.assertEqual(self.act("show", "GAM-001", "--text").splitlines(), [
            "- [ ] **GAM-001** — Jane — Existante 📅 2026-10-20", "acme / gamma · due 2026-10-20", "- source: s", "history: none",
            "brain/projects/clients/acme/missions/gamma/state/actions.md:4"])
        # the text is far shorter than the JSON, which repeats every sub-bullet twice
        shown = self.act("show", "GAM-008")
        self.assertEqual(len(shown["details"]), len(shown["notes"]))
        self.assertLess(len(self.act("show", "GAM-008", "--text", "--last", "0").split()), len(json.dumps(shown, ensure_ascii=False, indent=2).split()) / 2)

    def test_show_text_keeps_undated_entries_due_notes_closures_and_archives(self) -> None:
        self.register.write_text(REGISTER.replace("## Done\n", (
            "## Done\n- [x] **GAM-002** — Jane — Livrée ➕ 2026-10-01 ✅ 2026-10-12\n    - due: before the committee\n"
            "    - 10/10: first draft\n        - reviewed by Owner\n    - done: sent by mail on 12/10\n"
        )), encoding="utf-8")
        where = self.register.resolve().as_posix()  # a brain outside the Work root: its full path
        self.assertEqual(self.act("show", "GAM-002", "--text").splitlines(), [
            "- [x] **GAM-002** — Jane — Livrée ➕ 2026-10-01 ✅ 2026-10-12",
            "acme / gamma · due before the committee · created 2026-10-01 · closed 2026-10-12",
            "history, 2 entries:", "- 10/10: first draft", "    - reviewed by Owner", "- done: sent by mail on 12/10",
            f"{where}:8",
        ])
        self.assertEqual(self.act("show", "GAM-002", "--text", "--last", "1").splitlines()[2:4], ["history, last 1 of 2:", "- done: sent by mail on 12/10"])
        self.register.write_text(self.text().replace("due: before the committee", "due: —"), encoding="utf-8")  # a due note that says nothing
        self.assertEqual(self.act("show", "GAM-002", "--text").splitlines()[1], "acme / gamma · created 2026-10-01 · closed 2026-10-12")
        self.act("archive", "--write", "--today", "2026-12-01")
        archive = self.register.resolve().with_name("actions-archive-2026.md").as_posix()
        self.assertEqual(self.act("show", "GAM-002", "--text").splitlines()[-1], f"{archive}:6 (archived)")
        self.assertEqual(self.act("show", "GAM-002", "--text", "--last", "-1", code=2)["error"], "--last must be zero or positive.")
        self.assertEqual(self.act("show", "GAM-002", "--last", "2", code=2)["error"], "--last goes with --text.")
        self.assertEqual(self.act("show", "GAM-404", "--text", code=3)["kind"], "not_found")  # an error stays JSON

    def test_show_json_is_the_default_and_is_unchanged(self) -> None:
        def version(text: str) -> str:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        line = "- [ ] **GAM-001** — Jane — Existante 📅 2026-10-20"
        expected = {
            "id": "GAM-001", "state": " ", "owner": "Jane", "title": "Existante", "raw_title": "Existante", "group": "", "priority": "",
            "created": "", "created_at": "", "updated_at": "", "due": "2026-10-20", "scheduled": "", "done": "", "project": "acme / gamma",
            "register": "projects/clients/acme/missions/gamma/state/actions.md", "line": 4, "version": version(line),
            "details": ["- source: s"], "notes": [{"index": 0, "text": "- source: s", "deletable": False}],
            "details_version": version(f"{line}\n    - source: s"),
        }
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), "show", "GAM-001"], env=self.env, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.stdout, json.dumps(expected, ensure_ascii=False, indent=2) + "\n")  # the bytes tasks-web reads

    def test_list_due_before_and_limit(self) -> None:
        self.create(due="2026-10-15")  # GAM-008
        self.create(due="2026-10-25")  # GAM-009
        self.create()  # GAM-010, no due date
        def ids(*args: str) -> list[str]:
            return [a["id"] for a in self.act("list", *args)]

        self.assertEqual(ids(), ["GAM-001", "GAM-008", "GAM-009", "GAM-010"])  # default unchanged: register order, no cap
        self.assertEqual(ids("--due-before", "2026-10-25"), ["GAM-008", "GAM-001"])  # strictly before, earliest first, undated left out
        self.assertEqual(ids("--due-before", "2026-10-15"), [])
        self.assertEqual(ids("--due-before", "2026-12-01", "--limit", "2"), ["GAM-008", "GAM-001"])
        self.assertEqual(ids("--limit", "3"), ["GAM-001", "GAM-008", "GAM-009"])
        self.assertEqual(ids("--limit", "0"), [])
        self.act("update", "GAM-008", "--state", "done")
        self.assertEqual(ids("--due-before", "2026-12-01"), ["GAM-001", "GAM-009"])  # the state filter still applies (open by default)
        self.assertEqual(ids("--due-before", "2026-12-01", "--state", "all"), ["GAM-008", "GAM-001", "GAM-009"])
        table = self.act("list", "--due-before", "2026-10-21", "--table")
        self.assertEqual(table.splitlines(), ["[ ] GAM-001 — Jane — Existante 📅 2026-10-20  (acme / gamma)"])
        self.assertEqual(self.act("list", "--due-before", "25/10/2026", code=2)["kind"], "bad_request")
        self.assertEqual(self.act("list", "--limit", "-1", code=2)["kind"], "bad_request")


class ActionMoreCommandsTest(unittest.TestCase):
    """history edit, move between registers of a client, check (same fixture as ActionCommandTest)."""

    setUp = ActionCommandTest.setUp
    tearDown = ActionCommandTest.tearDown
    act = ActionCommandTest.act
    text = ActionCommandTest.text
    create = ActionCommandTest.create

    def test_history_edit_keeps_date_and_children_and_protects_metadata(self) -> None:
        self.create()
        self.act("history", "add", "GAM-008", "--text", "brouillon", "--date", "2026-10-12")
        index = len(self.act("show", "GAM-008")["notes"]) - 1
        self.act("history", "edit", "GAM-008", "--index", str(index), "--text", "version finale", now="2026-10-13 18:10")
        shown = self.act("show", "GAM-008")
        self.assertEqual(shown["notes"][index]["text"], "- 12/10: version finale")
        self.assertEqual(shown["updated_at"], "2026-10-13 18:10")
        self.act("history", "edit", "GAM-008", "--index", str(index), "--text", "redatée", "--date", "2026-10-11")
        self.assertEqual(self.act("show", "GAM-008")["notes"][index]["text"], "- 11/10: redatée")
        self.assertEqual(self.act("history", "edit", "GAM-008", "--index", "0", "--text", "x", code=2)["kind"], "bad_request")

    def test_move_within_client_rewrites_links_and_refuses_other_client(self) -> None:
        other = self.brain / "projects/clients/acme/missions/delta/state"
        other.mkdir(parents=True)
        (other / "actions.md").write_text("# Actions — Delta\n\n## Open\n\n## Done\n\n## Cancelled\n", encoding="utf-8")
        self.create()
        result = self.act("move", "GAM-008", "--to", "acme/delta", now="2026-10-14 08:00")
        self.assertEqual((result["from"], result["register"]), ("projects/clients/acme/missions/gamma/state/actions.md",
                                                             "projects/clients/acme/missions/delta/state/actions.md"))
        moved = (other / "actions.md").read_text(encoding="utf-8")
        self.assertIn("- [ ] **GAM-008** — Owner — Préparer la démo ➕ 2026-10-13\n    - source: [CR](../../gamma/sources/cr.md)", moved)
        self.assertIn("    - updated: 2026-10-14 08:00", moved)
        self.assertIn("    - 14/10: moved from acme / gamma", moved)
        self.assertNotIn("GAM-008", self.text())
        foreign = self.brain / "projects/clients/beta/missions/one/state"
        foreign.mkdir(parents=True)
        (foreign / "actions.md").write_text("# Actions\n\n## Open\n", encoding="utf-8")
        self.assertEqual(self.act("move", "GAM-001", "--to", "beta/one", code=2)["kind"], "bad_request")

    def test_check_reports_errors_and_warnings(self) -> None:
        self.assertIn("0 error(s), 0 warning(s)", self.act("check"))
        self.register.write_text(REGISTER.replace("## Done\n", "## Done\n- [x] **GAM-001** — Jane — Doublon ✅ 2026-10-01\n"
                                                  "- [x] **GAM-002** — Jane — Sans date\n- [ ] **GAM-003** — Jane — Ouverte ✅ 2026-10-01\n"
                                                  "- [ ] **GAM-004** — Jane — Date 📅 2026-02-30\n- [?] **GAM-005** — Jane — État inconnu\n"), encoding="utf-8")
        out = self.act("check", code=1)
        for expected in ("GAM-001 already present", "GAM-003 open but carries a closing date", "GAM-004 invalid 📅 date",
                         "malformed action line", "GAM-002 closed without a ✅/❌ date", "GAM-002 without a source sub-bullet"):
            self.assertIn(expected, out)


class ActionGroupTest(unittest.TestCase):
    """The optional `#group/<slug>` group tag: parse, rewrite, --group, check (same fixture as ActionCommandTest)."""

    setUp = ActionCommandTest.setUp
    tearDown = ActionCommandTest.tearDown
    act = ActionCommandTest.act
    text = ActionCommandTest.text
    create = ActionCommandTest.create

    def line(self, action_id: str) -> str:
        return next(line for line in self.text().splitlines() if f"**{action_id}**" in line)

    def test_parse_splits_the_trailing_tag_from_the_title(self) -> None:
        self.register.write_text(REGISTER.replace(
            "Existante 📅 2026-10-20", "Atelier [CR](x.md) #group/atelier-ingestion ⏫ ➕ 2026-10-12 📅 2026-10-20 ⏳ 2026-10-18"), encoding="utf-8")
        shown = self.act("show", "GAM-001")
        self.assertEqual((shown["group"], shown["title"], shown["raw_title"], shown["priority"], shown["due"]),
                         ("atelier-ingestion", "Atelier CR", "Atelier [CR](x.md)", "⏫", "2026-10-20"))

    def test_no_group_by_default_and_stray_tags_stay_in_the_title(self) -> None:
        self.assertEqual(self.act("show", "GAM-001")["group"], "")
        for title, group in (("Ouvre #group/a puis ferme", ""), ("Fin #group/Mauvais_Slug", ""), ("Deux #group/a #group/b", "b"),
                             ("Trop long #group/" + "a" * 41, "")):
            self.register.write_text(REGISTER.replace("Existante", title), encoding="utf-8")
            shown = self.act("show", "GAM-001")
            self.assertEqual(shown["group"], group, title)
            self.assertEqual(shown["raw_title"], title if not group else "Deux #group/a", title)

    def test_create_writes_the_tag_before_the_emojis_and_list_shows_it(self) -> None:
        result = self.create(group="atelier-ingestion", priority="high", due="2026-10-20")
        self.assertEqual(result["line"], "- [ ] **GAM-008** — Owner — Préparer la démo #group/atelier-ingestion ⏫ ➕ 2026-10-13 📅 2026-10-20")
        self.assertIn(result["line"] + "\n", self.text())
        self.assertEqual(self.act("list", "--project", "acme/gamma")[1]["group"], "atelier-ingestion")
        self.assertIn("[group: atelier-ingestion]", self.act("list", "--table"))
        self.assertNotIn("#group/", self.line("GAM-001"))

    def test_update_sets_changes_removes_and_keeps_the_group(self) -> None:
        self.act("update", "GAM-001", "--group", "lot-un")
        self.assertEqual(self.line("GAM-001"), "- [ ] **GAM-001** — Jane — Existante #group/lot-un 📅 2026-10-20")
        self.act("update", "GAM-001", "--owner", "Marie", "--due", "2026-10-22")
        self.assertEqual(self.line("GAM-001"), "- [ ] **GAM-001** — Marie — Existante #group/lot-un 📅 2026-10-22")
        self.act("update", "GAM-001", "--title", "Renommée", "--state", "x", "--closed-on", "2026-10-14")
        self.assertEqual(self.line("GAM-001"), "- [x] **GAM-001** — Marie — Renommée #group/lot-un 📅 2026-10-22 ✅ 2026-10-14")
        self.assertEqual(self.act("show", "GAM-001")["group"], "lot-un")
        self.act("update", "GAM-001", "--group", "lot-deux")
        self.assertIn("Renommée #group/lot-deux 📅", self.line("GAM-001"))
        result = self.act("update", "GAM-001", "--group", "")
        self.assertEqual(result["label"], "edit of GAM-001")
        self.assertEqual(self.line("GAM-001"), "- [x] **GAM-001** — Marie — Renommée 📅 2026-10-22 ✅ 2026-10-14")

    def test_update_without_group_leaves_an_ungrouped_line_byte_for_byte(self) -> None:
        before = self.line("GAM-001")
        self.act("update", "GAM-001", "--owner", "Jane")  # same value: nothing changes, not even the stamp
        self.assertEqual(self.line("GAM-001"), before)
        self.assertEqual(self.text(), REGISTER)
        self.create(priority="low", due="2026-10-14")
        created = self.line("GAM-008")
        self.act("update", "GAM-008", "--state", "in-progress")
        self.assertEqual(self.line("GAM-008"), created.replace("[ ]", "[/]"))
        self.act("update", "GAM-008", "--state", "todo")
        self.assertEqual(self.line("GAM-008"), created)

    def test_invalid_slug_and_title_ending_with_a_tag_are_refused(self) -> None:
        for bad in ("Atelier Ingestion", "atelier_ingestion", "-a", "a-", "a--b", "é", "a" * 41, "#group/a"):
            self.assertEqual(self.act("update", "GAM-001", f"--group={bad}", code=2)["kind"], "bad_request", bad)
            self.assertEqual(self.act("create", "--project", "acme/gamma", "--title", "T", "--owner", "A", "--source", "s",
                                      f"--group={bad}", code=2)["kind"], "bad_request", bad)
        self.act("update", "GAM-001", "--group", "a" * 40)  # the limit itself is fine
        self.assertEqual(self.act("update", "GAM-001", "--title", "Titre #group/autre", code=2)["kind"], "bad_request")
        self.assertEqual(self.act("create", "--project", "acme/gamma", "--title", "Titre #group/autre", "--owner", "A",
                                  "--source", "s", code=2)["kind"], "bad_request")
        self.assertEqual(self.act("update", "GAM-001", "--title", "Avec #group/x au milieu")["id"], "GAM-001")  # not a trailing tag
        self.assertEqual(self.act("show", "GAM-001")["group"], "a" * 40)

    def test_check_warns_about_several_invalid_or_misplaced_tags(self) -> None:
        self.assertIn("0 error(s), 0 warning(s)", self.act("check"))
        self.act("update", "GAM-001", "--group", "valide")
        self.assertIn("0 error(s), 0 warning(s)", self.act("check"))
        self.register.write_text(
            REGISTER.replace("## Open\n", "## Open\n- [ ] **GAM-002** — Jane — Deux #group/a #group/b\n    - source: s\n"
                             "- [ ] **GAM-003** — Jane — Mauvais #group/Mauvais_Slug\n    - source: s\n"
                             "- [ ] **GAM-004** — Jane — Au #group/milieu du titre\n    - source: s\n"), encoding="utf-8")
        out = self.act("check")  # warnings only: exit code 0
        self.assertIn("GAM-002 several #group/ tags", out)
        self.assertIn("GAM-003 invalid group slug #group/", out)
        self.assertIn("GAM-004 tag #group/milieu not at the end of the title", out)
        self.assertIn("0 error(s), 3 warning(s)", out)

    def test_sweep_archive_move_history_and_delete_keep_the_tag(self) -> None:
        other = self.brain / "projects/clients/acme/missions/delta/state"
        other.mkdir(parents=True)
        (other / "actions.md").write_text("# Actions — Delta\n\n## Open\n\n## Done\n\n## Cancelled\n", encoding="utf-8")
        self.act("update", "GAM-001", "--group", "lot-un")
        self.act("history", "add", "GAM-001", "--text", "une note")
        self.assertIn("Existante #group/lot-un 📅", self.line("GAM-001"))
        self.act("update", "GAM-001", "--state", "x", "--closed-on", "2026-01-05")
        self.assertIn("## Done\n- [x] **GAM-001** — Jane — Existante #group/lot-un 📅 2026-10-20 ✅ 2026-01-05", self.text())
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), "archive", "--write", "--today", "2026-10-13"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = (self.folder / "state/actions-archive-2026.md").read_text(encoding="utf-8")
        self.assertIn("Existante #group/lot-un 📅 2026-10-20 ✅ 2026-01-05", archive)
        self.create(group="lot-deux", prefix="GAM")  # the archive emptied the register: its prefix is given again
        self.act("move", "GAM-008", "--to", "acme/delta")
        self.assertIn("- [ ] **GAM-008** — Owner — Préparer la démo #group/lot-deux ➕", (other / "actions.md").read_text(encoding="utf-8"))
        self.assertEqual(self.act("show", "GAM-008")["group"], "lot-deux")
        self.act("delete", "GAM-008")
        self.assertNotIn("GAM-008", (other / "actions.md").read_text(encoding="utf-8"))


class ActionHistoryCapTest(unittest.TestCase):
    """The 35-word cap of a history entry, the doubled date and the exact duplicate (same fixture as ActionCommandTest)."""

    setUp = ActionCommandTest.setUp
    tearDown = ActionCommandTest.tearDown
    act = ActionCommandTest.act
    text = ActionCommandTest.text

    def history(self) -> list[str]:
        return [note["text"] for note in self.act("show", "GAM-001")["notes"]]

    def test_add_and_edit_accept_35_words_and_refuse_36_even_in_dry_run(self) -> None:
        link = "[minutes of the acme demo](../sources/2026-10/2026-10-12-cr-a-very-long-slug.md)"
        self.act("history", "add", "GAM-001", "--text", " ".join(["word"] * 30) + " " + link)  # 30 + 5 label words
        before = self.text()
        for args in (("--text", " ".join(["word"] * 36)), ("--text", " ".join(["word"] * 31) + " " + link), ("--text", " ".join(["word"] * 36), "--dry-run")):
            error = self.act("history", "add", "GAM-001", *args, code=2)
            self.assertEqual(error["kind"], "bad_request")
            self.assertIn("36 words; the cap is 35", error["error"])
            self.assertIn("one change of state, owner, due date or blocker", error["error"])
        error = self.act("history", "edit", "GAM-001", "--index", "2", "--text", " ".join(["word"] * 36), code=2)  # 0 source, 1 updated
        self.assertIn("36 words; the cap is 35", error["error"])
        self.assertEqual(self.text(), before)
        self.act("history", "edit", "GAM-001", "--index", "2", "--text", " ".join(["word"] * 35))
        self.assertEqual(self.history()[2], "- 13/10: " + " ".join(["word"] * 35))

    def test_a_leading_date_equal_to_the_entry_is_dropped_and_another_is_refused(self) -> None:
        self.act("history", "add", "GAM-001", "--text", "13/10: asked Jane Doe for the slides")  # today is 13/10
        self.act("history", "add", "GAM-001", "--text", "12/10 : slides received", "--date", "2026-10-12")
        self.assertEqual(self.history()[2:], ["- 13/10: asked Jane Doe for the slides", "- 12/10: slides received"])
        before = self.text()
        error = self.act("history", "add", "GAM-001", "--text", "11/10: call planned", code=2)
        self.assertIn("starts with the date 11/10 but the entry is dated 13/10", error["error"])
        self.assertIn("--date", error["error"])
        error = self.act("history", "edit", "GAM-001", "--index", "3", "--text", "13/10: slides received", code=2)
        self.assertIn("entry is dated 12/10", error["error"])
        self.assertEqual(self.text(), before)
        self.act("history", "edit", "GAM-001", "--index", "3", "--text", "12/10: slides received twice")
        self.act("history", "edit", "GAM-001", "--index", "2", "--text", "10/10: asked earlier", "--date", "2026-10-10")
        self.assertEqual(self.history()[2:], ["- 10/10: asked earlier", "- 12/10: slides received twice"])
        self.assertEqual(self.act("history", "add", "GAM-001", "--text", "13/10:", code=2)["kind"], "bad_request")  # nothing left

    def test_an_exact_duplicate_writes_nothing_and_says_unchanged(self) -> None:
        first = self.act("history", "add", "GAM-001", "--text", "owner changed to Jane Doe", "--date", "2026-10-12")
        self.assertIs(first["unchanged"], False)
        before = self.register.read_bytes()
        again = self.act("history", "add", "GAM-001", "--text", "owner changed to Jane Doe", "--date", "2026-10-12", now="2026-10-14 08:00")
        self.assertEqual((again["unchanged"], again["updated_changed"], again["label"]), (True, False, "note already in GAM-001"))
        self.assertEqual(self.register.read_bytes(), before)
        self.act("history", "add", "GAM-001", "--text", "owner changed to Jane Doe", "--date", "2026-10-13")  # another date: a new entry
        self.assertEqual(self.history()[2:], ["- 12/10: owner changed to Jane Doe", "- 13/10: owner changed to Jane Doe"])


SUBTASK_REGISTER = """# Actions — Gamma

## Open
- [ ] **GAM-001** — Jane Doe — Plan the workshop 📅 2026-10-20
    - source: s
    - created: 2026-10-01 09:00
    - updated: 2026-10-02 09:00
    - 02/10: first note
        - a detail of the first note
    - 03/10: second note

## Done

## Cancelled
"""


class ActionSubtaskTest(unittest.TestCase):
    """Subtasks: checkbox sub-bullets right under the action line, written with `subtask`, kept apart from the history."""

    tearDown = ActionCommandTest.tearDown
    act = ActionCommandTest.act
    text = ActionCommandTest.text

    def setUp(self) -> None:
        ActionCommandTest.setUp(self)
        self.register.write_text(SUBTASK_REGISTER, encoding="utf-8")

    def block(self, action_id: str = "GAM-001") -> list[str]:
        lines = self.text().splitlines()
        start = next(number for number, line in enumerate(lines) if f"**{action_id}**" in line)
        end = start + 1
        while end < len(lines) and lines[end].startswith("    "):
            end += 1
        return lines[start:end]

    def three(self) -> None:
        for text in ("Draft the agenda", "Book the room", "Send the invitation"):
            self.act("subtask", "add", "GAM-001", "--text", text)

    def test_add_toggle_edit_move_remove_write_under_the_line_and_stamp_without_history(self) -> None:
        history = self.act("show", "GAM-001")["notes"]
        result = self.act("subtask", "add", "GAM-001", "--text", "Book the room", now="2026-10-13 15:00")
        self.assertEqual((result["label"], result["index"], result["subtask"], result["subtasks_total"], result["unchanged"]),
                         ("subtask added to GAM-001", 0, {"index": 0, "text": "Book the room", "done": False, "done_on": ""}, 1, False))
        self.act("subtask", "add", "GAM-001", "--text", "Draft the agenda", "--position", "0")
        self.act("subtask", "add", "GAM-001", "--text", "Send the [invitation](../sources/x.md)")
        result = self.act("subtask", "toggle", "GAM-001", "--index", "1", now="2026-10-14 09:00")
        self.assertEqual((result["label"], result["subtasks_done"], result["subtask"]["done_on"]), ("subtask ticked on GAM-001", 1, "2026-10-14"))
        self.assertEqual(result["details_version"], self.act("show", "GAM-001")["details_version"])
        self.assertEqual(self.block()[:5], [
            "- [ ] **GAM-001** — Jane Doe — Plan the workshop 📅 2026-10-20",
            "    - [ ] Draft the agenda", "    - [x] Book the room ✅ 2026-10-14", "    - [ ] Send the [invitation](../sources/x.md)",
            "    - source: s"])
        self.assertIn("    - updated: 2026-10-14 09:00", self.block())
        before = self.register.read_bytes()
        self.assertIs(self.act("subtask", "toggle", "GAM-001", "--index", "1", "--done")["unchanged"], True)  # idempotent
        self.assertIs(self.act("subtask", "toggle", "GAM-001", "--index", "0", "--undone")["unchanged"], True)
        self.assertEqual(self.register.read_bytes(), before)
        self.act("subtask", "edit", "GAM-001", "--index", "1", "--text", "Book the large room")
        self.assertIn("    - [x] Book the large room ✅ 2026-10-14", self.block())  # the state and its date stay
        result = self.act("subtask", "move", "GAM-001", "--index", "2", "--to", "0")
        self.assertEqual([item["text"] for item in result["subtasks"]],
                         ["Send the [invitation](../sources/x.md)", "Draft the agenda", "Book the large room"])
        result = self.act("subtask", "toggle", "GAM-001", "--index", "2", now="2026-10-15 10:00")
        self.assertEqual((result["label"], result["subtask"]["done_on"]), ("subtask unticked on GAM-001", ""))
        self.assertIn("    - [ ] Book the large room", self.block())  # the ✅ date is gone
        result = self.act("subtask", "remove", "GAM-001", "--index", "0", now="2026-10-15 11:00")
        self.assertEqual((result["label"], result["removed"]["text"], result["subtasks_total"]),
                         ("subtask removed from GAM-001", "Send the [invitation](../sources/x.md)", 2))
        self.assertEqual(self.block()[1:3], ["    - [ ] Draft the agenda", "    - [ ] Book the large room"])
        self.assertIn("    - updated: 2026-10-15 11:00", self.block())
        self.assertEqual([note for note in self.act("show", "GAM-001")["notes"] if not note["text"].startswith("- updated")],
                         [note for note in history if not note["text"].startswith("- updated")])  # no history entry
        self.act("subtask", "remove", "GAM-001", "--index", "0")
        self.act("subtask", "remove", "GAM-001", "--index", "0")
        self.assertEqual(self.text(), SUBTASK_REGISTER.replace("2026-10-02 09:00", "2026-10-13 14:32"))

    def test_history_indices_and_the_show_json_ignore_the_subtasks(self) -> None:
        before = self.act("show", "GAM-001")
        self.assertNotIn("subtasks", before)
        self.three()
        shown = self.act("show", "GAM-001")
        self.assertEqual([(note["index"], note["deletable"]) for note in shown["notes"]],
                         [(note["index"], note["deletable"]) for note in before["notes"]])
        self.assertEqual([note["text"] for note in shown["notes"]][3:], ["- 02/10: first note\n    - a detail of the first note", "- 03/10: second note"])
        self.assertEqual((shown["subtasks_done"], shown["subtasks_total"], [item["index"] for item in shown["subtasks"]]), (0, 3, [0, 1, 2]))
        self.assertEqual(list(shown)[list(shown).index("notes"):], ["notes", "subtasks", "subtasks_done", "subtasks_total", "details_version"])
        self.act("history", "edit", "GAM-001", "--index", "4", "--text", "second note, reworded")
        self.assertIn("    - 03/10: second note, reworded", self.block())
        self.act("history", "add", "GAM-001", "--text", "room booked", "--date", "2026-10-12")
        self.assertEqual(self.block()[-1], "    - 12/10: room booked")
        self.act("history", "remove", "GAM-001", "--index", "3")
        self.assertNotIn("first note", self.text())
        self.assertEqual(self.act("history", "remove", "GAM-001", "--index", "5", code=2)["error"], "Note not found.")
        self.assertEqual(self.act("show", "GAM-001")["subtasks_total"], 3)  # no history command reached a subtask
        self.assertEqual(self.block()[1:4], ["    - [ ] Draft the agenda", "    - [ ] Book the room", "    - [ ] Send the invitation"])

    def test_obsidian_ticks_and_hand_made_subtasks_are_read_wherever_they_sit(self) -> None:
        self.register.write_text(SUBTASK_REGISTER.replace(
            "    - source: s\n", "    - [x] Ticked in Obsidian ✅ 2026-10-12\n    - source: s\n").replace(
            "    - 03/10: second note\n", "    - 03/10: second note\n    - [ ] Added by hand at the end\n"), encoding="utf-8")
        shown = self.act("show", "GAM-001")
        self.assertEqual(shown["subtasks"], [{"index": 0, "text": "Ticked in Obsidian", "done": True, "done_on": "2026-10-12"},
                                             {"index": 1, "text": "Added by hand at the end", "done": False, "done_on": ""}])
        self.assertEqual(len(shown["notes"]), 5)
        self.act("history", "add", "GAM-001", "--text", "agenda sent")  # after the last history entry, not after the subtask
        self.assertEqual(self.block()[-2:], ["    - 13/10: agenda sent", "    - [ ] Added by hand at the end"])
        self.assertIn("subtask after other sub-bullets", self.act("check"))
        self.act("subtask", "toggle", "GAM-001", "--index", "0")  # any subtask write puts them back under the line
        self.assertEqual(self.block()[1:4], ["    - [ ] Ticked in Obsidian", "    - [ ] Added by hand at the end", "    - source: s"])
        self.assertEqual(self.block()[-1], "    - 13/10: agenda sent")
        self.assertIn("0 error(s), 0 warning(s)", self.act("check"))

    def test_invalid_requests_are_refused_and_write_nothing(self) -> None:
        self.three()
        version = self.act("show", "GAM-001")["details_version"]
        before = self.text()
        for args, message in (
                (("add", "GAM-001", "--text", " ".join(["step"] * 16)), "Subtask has 16 words; the cap is 15"),
                (("add", "GAM-001", "--text", "Book 📅 2026-10-20"), "no Tasks metadata"),
                (("add", "GAM-001", "--text", "Book ⏫"), "no Tasks metadata"),
                (("add", "GAM-001", "--text", "See **GAM-002**"), "no action ID"),
                (("add", "GAM-001", "--text", "two\nlines"), "on one line"),
                (("add", "GAM-001", "--text", "Late", "--position", "4"), "The position must be 0 to 3."),
                (("toggle", "GAM-001", "--index", "3"), "Subtask not found."),
                (("edit", "GAM-001", "--index", "-1", "--text", "x"), "Subtask not found."),
                (("move", "GAM-001", "--index", "0", "--to", "3"), "The target index must be 0 to 2."),
                (("add", "GAM-001", "--text", " ".join(["step"] * 16), "--dry-run"), "the cap is 15")):
            error = self.act("subtask", *args, code=2)
            self.assertEqual(error["kind"], "bad_request", args)
            self.assertIn(message, error["error"], args)
        self.assertEqual(self.act("subtask", "add", "GAM-001", "--text", "Late", "--expect-details-version", "stale", code=4)["kind"], "conflict")
        self.assertEqual(self.act("subtask", "add", "GAM-404", "--text", "Late", code=3)["kind"], "not_found")
        self.act("subtask", "remove", "GAM-001", "--index", "0", "--expect-details-version", version, "--dry-run")
        self.assertEqual(self.text(), before)
        for number in range(7):
            self.act("subtask", "add", "GAM-001", "--text", f"Step {number}")
        error = self.act("subtask", "add", "GAM-001", "--text", "One too many", code=2)
        self.assertIn("at most 10 subtasks", error["error"])
        self.assertEqual(self.act("show", "GAM-001")["subtasks_total"], 10)

    def test_closing_with_open_subtasks_warns_and_leaves_them_open(self) -> None:
        self.three()
        self.act("subtask", "toggle", "GAM-001", "--index", "0")
        result = self.act("update", "GAM-001", "--state", "done")
        self.assertEqual(result["warnings"], ["2 subtasks of GAM-001 still open, left unticked."])
        self.assertIn("## Done\n- [x] **GAM-001**", self.text())
        self.assertEqual([item["done"] for item in self.act("show", "GAM-001")["subtasks"]], [True, False, False])
        self.assertNotIn("warnings", self.act("update", "GAM-001", "--title", "Plan the workshop again"))  # not a closure
        self.assertNotIn("warnings", self.act("update", "GAM-001", "--state", "todo"))
        self.act("subtask", "remove", "GAM-001", "--index", "2")
        result = self.act("update", "GAM-001", "--state", "cancelled")
        self.assertEqual(result["warnings"], ["1 subtask of GAM-001 still open, left unticked."])
        self.act("update", "GAM-001", "--state", "todo")
        self.act("subtask", "toggle", "GAM-001", "--index", "1")
        self.assertNotIn("warnings", self.act("update", "GAM-001", "--state", "done"))  # every subtask ticked

    def test_list_table_and_show_text_give_the_progress(self) -> None:
        self.three()
        self.act("subtask", "toggle", "GAM-001", "--index", "1", now="2026-10-14 09:00")
        self.act("create", "--project", "acme/gamma", "--title", "No checklist", "--owner", "Jane Doe", "--source", "s")
        listed = self.act("list")
        self.assertEqual(listed[0]["subtasks"], {"done": 1, "total": 3})
        self.assertNotIn("subtasks", listed[1])
        self.assertEqual(self.act("list", "--table").splitlines(), [
            "[ ] GAM-001 — Jane Doe — Plan the workshop 1/3 📅 2026-10-20  (acme / gamma)",
            "[ ] GAM-008 — Jane Doe — No checklist  (acme / gamma)"])
        self.assertEqual(self.act("show", "GAM-001", "--text").splitlines()[1:7], [
            "acme / gamma · due 2026-10-20 · created 2026-10-01 09:00 · updated 2026-10-14 09:00",
            "subtasks, 1 of 3 done:", "- [ ] Draft the agenda", "- [x] Book the room ✅ 2026-10-14", "- [ ] Send the invitation",
            "- source: s"])
        self.assertEqual(self.act("show", "GAM-001", "--text").splitlines()[7:10], ["history, 2 entries:",
                         "- 02/10: first note", "    - a detail of the first note"])

    def test_check_reads_subtasks_apart_from_the_source(self) -> None:
        self.register.write_text(SUBTASK_REGISTER.replace("    - source: s\n", "    - [ ] A step, not a source\n"), encoding="utf-8")
        self.assertIn("GAM-001 without a source sub-bullet", self.act("check"))
        self.register.write_text(SUBTASK_REGISTER.replace("    - source: s\n", "".join(f"    - [ ] Step {n}\n" for n in range(11))
                                                          + "    - [/] Half done\n    - [ ] Due 📅 2026-10-20\n    - [x] Done ✅ 2026-10-12\n"
                                                          + "    - [ ] See **GAM-002** first\n    - source: s\n")
                                 .replace("    - 03/10: second note\n", "    - 03/10: second note\n    - [ ] Too low\n"), encoding="utf-8")
        out = self.act("check")  # warnings only: exit code 0
        for expected in ("GAM-001 has 16 subtasks (at most 10)", "GAM-001 subtask in state [/]", "GAM-001 subtask with Tasks metadata",
                         "GAM-001 subtask carrying an action ID", "GAM-001 subtask after other sub-bullets"):
            self.assertIn(expected, out)
        self.assertIn("0 error(s), 5 warning(s)", out)  # the done date Obsidian appends is no metadata

    def test_sweep_archive_move_and_delete_carry_the_subtasks(self) -> None:
        other = self.brain / "projects/clients/acme/missions/delta/state"
        other.mkdir(parents=True)
        (other / "actions.md").write_text("# Actions — Delta\n\n## Open\n\n## Done\n\n## Cancelled\n", encoding="utf-8")
        self.three()
        self.act("subtask", "toggle", "GAM-001", "--index", "0")
        before = self.text()
        self.assertIn("Total sweep: 0 action(s)", self.act("sweep", "--write"))  # a ticked subtask is not a closed action
        self.assertEqual(self.text(), before)
        self.register.write_text(before.replace("- [ ] **GAM-001**", "- [x] **GAM-001**").replace("2026-10-20\n", "2026-10-20 ✅ 2026-01-05\n", 1),
                                 encoding="utf-8")  # ticked in Obsidian
        block = self.block()
        self.act("sweep", "--write")
        self.assertIn("## Done\n" + "\n".join(block) + "\n", self.text())
        self.act("archive", "--write", "--today", "2026-10-13")
        archive = (self.register.parent / "actions-archive-2026.md").read_text(encoding="utf-8")
        self.assertIn("\n".join(block) + "\n", archive)
        self.assertNotIn("GAM-001", self.text())
        self.register.write_text(SUBTASK_REGISTER, encoding="utf-8")
        self.three()
        block = self.block()
        self.act("move", "GAM-001", "--to", "acme/delta", now="2026-10-14 08:00")
        moved = (other / "actions.md").read_text(encoding="utf-8")
        self.assertIn("\n".join(block[:4]) + "\n    - source: s\n", moved)
        self.assertIn("    - 03/10: second note\n    - 14/10: moved from acme / gamma\n", moved)
        self.act("delete", "GAM-001")
        self.assertEqual((other / "actions.md").read_text(encoding="utf-8"), "# Actions — Delta\n\n## Open\n\n## Done\n\n## Cancelled\n")


STAMPED_REGISTER = """# Actions — Gamma

## Open
- [ ] **GAM-001** — Jane — Existing action 📅 2026-10-20
    - source: s
    - created: 2026-10-01 09:00
    - updated: 2026-10-20 16:24
    - 02/10: first note
- [ ] **GAM-002** — Jane — Second action
    - source: s
    - created: 2026-10-02 10:00
    - updated: 2026-10-05 11:00
- [ ] **GAM-004** — Jane — Legacy action without stamps
    - source: s

## Done
- [x] **GAM-003** — Jane — Finished action ✅ 2026-10-10
    - source: s
    - created: 2026-10-03 10:00
    - updated: 2026-10-10 08:00

## Cancelled
"""

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


@unittest.skipUnless(shutil.which("git"), "git is required")
class ActionUpdatedStampTest(unittest.TestCase):
    """`updated:` reflects semantic changes against the task's last Git synchronization point."""

    act = ActionCommandTest.act

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name).resolve()
        self.brain = root / "brain"
        self.register = self.brain / "projects/clients/acme/missions/gamma/state/actions.md"
        self.register.parent.mkdir(parents=True)
        self.register.write_text(STAMPED_REGISTER, encoding="utf-8")
        # The ceiling keeps Git from finding a repository above the temporary folder.
        self.env = {**os.environ, **GIT_ENV, "GIT_CEILING_DIRECTORIES": str(root), "ACTION_NOW": "2026-10-26 11:17"}

    def text(self) -> str:
        return self.register.read_text(encoding="utf-8")

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                                cwd=self.brain, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def commit(self) -> None:
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "test: register")

    def stamp(self, action_id: str) -> str | None:
        lines = self.text().splitlines()
        start = next(number for number, line in enumerate(lines) if f"**{action_id}**" in line)
        for line in lines[start + 1:]:
            if not line.startswith("    "):
                break
            if line.startswith("    - updated: "):
                return line[len("    - updated: "):]
        return None

    def test_a_write_that_changes_nothing_keeps_updated_and_does_not_rewrite_the_file(self) -> None:
        before = self.register.stat()
        for args in (("update", "GAM-001", "--state", "todo", "--owner", "Jane", "--due", "2026-10-20"),
                     ("update", "GAM-001", "--title", "Existing action"),
                     ("update", "GAM-004", "--state", "todo"),
                     ("history", "edit", "GAM-001", "--index", "3", "--text", "first note")):
            self.assertIs(self.act(*args)["updated_changed"], False, args)
        self.assertEqual(self.text(), STAMPED_REGISTER)
        after = self.register.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.commit()
        self.act("update", "GAM-002", "--owner", "Jane")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_noop_repairs_an_updated_stamp_left_dirty_by_an_earlier_edit(self) -> None:
        self.commit()
        self.register.write_text(STAMPED_REGISTER.replace("    - updated: 2026-10-20 16:24\n",
                                                          "    - updated: 2026-10-26 11:17\n", 1), encoding="utf-8")
        result = self.act("update", "GAM-001", "--state", "todo", "--owner", "Jane", "--due", "2026-10-20")
        self.assertIs(result["updated_changed"], True)
        self.assertEqual(self.text(), STAMPED_REGISTER)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_trailing_whitespace_is_not_a_change(self) -> None:
        self.register.write_text(STAMPED_REGISTER.replace("Second action", "Second action   ").replace("    - source: s\n    - created: 2026-10-02", "    - source: s  \n    - created: 2026-10-02"), encoding="utf-8")
        result = self.act("update", "GAM-002", "--owner", "Jane")
        self.assertIs(result["updated_changed"], False)
        self.assertEqual(self.stamp("GAM-002"), "2026-10-05 11:00")

    def test_a_real_change_stamps_the_current_time(self) -> None:
        self.commit()
        result = self.act("update", "GAM-001", "--owner", "Marie")
        self.assertIs(result["updated_changed"], True)
        self.assertIn("- [ ] **GAM-001** — Marie — Existing action 📅 2026-10-20\n    - source: s\n    - created: 2026-10-01 09:00\n"
                      "    - updated: 2026-10-26 11:17\n", self.text())
        self.act("update", "GAM-001", "--owner", "Paul", now="2026-10-26 11:45")  # neither the previous nor the committed state
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:45")
        self.act("history", "add", "GAM-002", "--text", "called back", "--date", "2026-10-26", now="2026-10-26 12:00")
        self.assertEqual((self.stamp("GAM-002"), self.stamp("GAM-003")), ("2026-10-26 12:00", "2026-10-10 08:00"))
        self.assertIn("    - created: 2026-10-01 09:00\n", self.text())  # never touched

    def test_a_status_changed_then_changed_back_regains_the_synced_stamp(self) -> None:
        self.commit()
        self.assertIs(self.act("update", "GAM-001", "--state", "in-progress")["updated_changed"], True)
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:17")
        self.assertIs(self.act("update", "GAM-001", "--state", "todo", now="2026-10-26 11:30")["updated_changed"], True)
        self.assertEqual(self.stamp("GAM-001"), "2026-10-20 16:24")
        self.assertEqual(self.text(), STAMPED_REGISTER)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_the_reference_is_the_last_sync_not_an_unsent_local_commit(self) -> None:
        self.commit()
        branch = self.git("branch", "--show-current").strip()
        self.git("branch", "sync-point")
        self.git("config", f"branch.{branch}.remote", ".")
        self.git("config", f"branch.{branch}.merge", "refs/heads/sync-point")
        self.act("update", "GAM-001", "--owner", "Marie")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "test: unsent local change")

        self.act("update", "GAM-001", "--owner", "Jane", now="2026-10-26 11:30")
        self.assertEqual(self.text(), STAMPED_REGISTER)
        self.assertEqual(self.stamp("GAM-001"), "2026-10-20 16:24")

    def test_a_due_date_set_then_cleared_regains_the_committed_stamp(self) -> None:
        self.commit()
        self.act("update", "GAM-002", "--due", "2026-11-02")
        self.assertIn("- [ ] **GAM-002** — Jane — Second action 📅 2026-11-02\n", self.text())
        self.assertEqual(self.stamp("GAM-002"), "2026-10-26 11:17")
        self.act("update", "GAM-002", "--due", "", now="2026-10-26 11:30")
        self.assertEqual(self.text(), STAMPED_REGISTER)

    def test_a_note_added_then_deleted_regains_the_committed_stamp(self) -> None:
        self.commit()
        self.act("history", "add", "GAM-001", "--text", "sent the slides", "--date", "2026-10-26")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:17")
        index = len(self.act("show", "GAM-001")["notes"]) - 1
        self.act("history", "remove", "GAM-001", "--index", str(index), now="2026-10-26 11:30")
        self.assertEqual(self.text(), STAMPED_REGISTER)

    def test_a_note_edited_then_restored_regains_the_committed_stamp(self) -> None:
        self.commit()
        self.act("history", "edit", "GAM-001", "--index", "3", "--text", "first note, reworded")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:17")
        self.act("history", "edit", "GAM-001", "--index", "3", "--text", "first note", now="2026-10-26 11:30")
        self.assertEqual(self.text(), STAMPED_REGISTER)

    def test_a_title_edited_then_restored_regains_the_committed_stamp(self) -> None:
        self.commit()
        self.act("update", "GAM-001", "--title", "Renamed action")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:17")
        self.act("update", "GAM-001", "--title", "Existing action", now="2026-10-26 11:30")
        self.assertEqual(self.text(), STAMPED_REGISTER)

    def test_an_action_that_moved_section_and_came_back_regains_the_committed_stamp(self) -> None:
        self.commit()
        self.act("update", "GAM-003", "--state", "todo")  # reopened: moves to Open
        self.assertLess(self.text().index("**GAM-003**"), self.text().index("## Done"))
        self.assertEqual(self.stamp("GAM-003"), "2026-10-26 11:17")
        self.act("update", "GAM-003", "--state", "done", "--closed-on", "2026-10-10", now="2026-10-26 11:30")  # same closure again
        self.assertGreater(self.text().index("**GAM-003**"), self.text().index("## Done"))
        self.assertEqual(self.stamp("GAM-003"), "2026-10-10 08:00")
        self.assertEqual(self.text(), STAMPED_REGISTER)
        self.act("update", "GAM-003", "--state", "x", "--closed-on", "2026-10-11", now="2026-10-26 11:40")  # another closure date: a change
        self.assertEqual(self.stamp("GAM-003"), "2026-10-26 11:40")

    def test_without_a_git_repository_only_the_comparison_with_the_previous_state_applies(self) -> None:
        self.act("update", "GAM-001", "--state", "in-progress")
        self.act("update", "GAM-001", "--state", "todo", now="2026-10-26 11:30")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:30")  # nothing to restore: a change, stamped
        self.act("update", "GAM-001", "--state", "todo", now="2026-10-26 12:00")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:30")  # no change: kept

    def test_git_that_cannot_tell_is_ignored_quietly(self) -> None:
        self.git("init", "-q")  # a repository without any commit: HEAD does not exist
        self.act("update", "GAM-001", "--state", "in-progress")
        self.act("update", "GAM-001", "--state", "todo", now="2026-10-26 11:30")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:30")
        (self.brain / "other.md").write_text("x\n", encoding="utf-8")  # a commit that does not contain the register
        self.git("add", "other.md")
        self.git("commit", "-q", "-m", "test: other")
        self.act("update", "GAM-001", "--state", "in-progress", now="2026-10-26 11:40")
        self.act("update", "GAM-001", "--state", "todo", now="2026-10-26 11:50")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-26 11:50")

    def test_an_action_created_after_the_last_commit_is_stamped_now(self) -> None:
        self.commit()
        action_id = self.act("create", "--project", "acme/gamma", "--title", "New action", "--owner", "Jane", "--source", "s")["id"]
        self.assertEqual(action_id, "GAM-005")
        self.act("update", action_id, "--state", "in-progress", now="2026-10-26 11:30")
        self.act("update", action_id, "--state", "todo", now="2026-10-26 11:40")
        self.assertEqual(self.stamp(action_id), "2026-10-26 11:40")
        self.assertEqual(self.stamp("GAM-001"), "2026-10-20 16:24")

    def test_a_committed_action_without_updated_loses_the_line_it_was_given(self) -> None:
        self.commit()
        self.act("history", "add", "GAM-004", "--text", "asked for news", "--date", "2026-10-26")
        self.assertEqual(self.stamp("GAM-004"), "2026-10-26 11:17")
        index = len(self.act("show", "GAM-004")["notes"]) - 1
        self.act("history", "remove", "GAM-004", "--index", str(index), now="2026-10-26 11:30")
        self.assertIsNone(self.stamp("GAM-004"))
        self.assertEqual(self.text(), STAMPED_REGISTER)

    def test_move_keeps_stamping_because_it_adds_a_history_entry(self) -> None:
        other = self.brain / "projects/clients/acme/missions/delta/state"
        other.mkdir(parents=True)
        (other / "actions.md").write_text("# Actions — Delta\n\n## Open\n\n## Done\n\n## Cancelled\n", encoding="utf-8")
        self.commit()
        self.act("move", "GAM-001", "--to", "acme/delta")
        self.assertIn("    - updated: 2026-10-26 11:17\n", (other / "actions.md").read_text(encoding="utf-8"))


FRENCH_REGISTER = """# Actions — Gamma

## Ouvertes
- [x] **GAM-001** — Jane — Existante ✅ 2026-10-12
    - source: s

## Terminées

## Annulées
"""


class EarlierFrenchLabelsTest(unittest.TestCase):
    """The tools read only the English labels: a register still written with the French ones is converted by migrate-english.py."""

    tearDown, act = ActionCommandTest.tearDown, ActionCommandTest.act

    def setUp(self) -> None:
        ActionCommandTest.setUp(self)
        self.register.write_text(FRENCH_REGISTER, encoding="utf-8")

    def test_french_section_titles_are_not_understood(self) -> None:
        report = self.act("sweep")
        self.assertIn("GAM-001: filed under 'ouvertes', unknown section, left in place", report)
        self.assertEqual(self.register.read_text(encoding="utf-8"), FRENCH_REGISTER)


class DefaultBrainTest(unittest.TestCase):
    """Without --brain nor BRAIN_DIR, the tools act on the default brain of WORK_DIR (rule of tools/machine/work_config.py)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name).resolve() / "Work"
        self.make_brain("brain", "GAM")
        self.make_brain("brain-initech", "INI")
        self.env = {key: value for key, value in os.environ.items() if key not in ("BRAIN_DIR", "WORK_DIR")}
        self.env["WORK_DIR"] = str(self.work)

    def make_brain(self, name: str, prefix: str) -> None:
        brain = self.work / name
        (brain / ".data").mkdir(parents=True)
        (brain / "AGENTS.md").write_text("# test\n", encoding="utf-8")
        register = brain / "projects/clients/acme/missions/gamma/state/actions.md"
        register.parent.mkdir(parents=True)
        register.write_text(REGISTER.replace("GAM", prefix), encoding="utf-8")

    def listed(self, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), "list", "--project", "acme/gamma"], env={**self.env, **env},
                              capture_output=True, text=True)

    def ids(self, **env: str) -> list[str]:
        result = self.listed(**env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [item["id"] for item in json.loads(result.stdout)]

    def set_default(self, name: str) -> None:
        (self.work / "work-config.local.json").write_text(json.dumps({"version": 1, "defaultBrain": name}), encoding="utf-8")

    def test_brain_is_the_default_then_the_setting_then_the_only_brain(self) -> None:
        self.assertEqual(self.ids(), ["GAM-001"])
        self.set_default("brain-initech")
        self.assertEqual(self.ids(), ["INI-001"])
        (self.work / "work-config.local.json").unlink()
        (self.work / "brain").rename(self.work / "brain-old")
        result = self.listed()  # no `brain/` left and two brains: no default, so today's "missing" behaviour on Work/brain
        self.assertEqual(result.returncode, 3)
        self.assertIn(str(self.work / "brain/projects"), result.stdout)
        shutil.rmtree(self.work / "brain-old")
        self.assertEqual(self.ids(), ["INI-001"])  # the only brain

    def test_brain_dir_and_the_brain_option_still_win(self) -> None:
        self.set_default("brain-initech")
        self.assertEqual(self.ids(BRAIN_DIR=str(self.work / "brain")), ["GAM-001"])
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.work / "brain"), "list", "--project", "acme/gamma"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual([item["id"] for item in json.loads(result.stdout)], ["GAM-001"])

    def test_invalid_setting_is_reported_not_a_traceback(self) -> None:
        self.set_default("brain-nope")
        result = self.listed()
        self.assertEqual(result.returncode, 1)
        self.assertIn("defaultBrain brain-nope is not a brain", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.ids(BRAIN_DIR=str(self.work / "brain")), ["GAM-001"])  # BRAIN_DIR never reads the setting

    def test_the_work_relative_path_of_a_register_names_the_brain_folder(self) -> None:
        path = "brain-initech/projects/clients/acme/missions/gamma/state/actions.md"
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.work / "brain-initech"), "list", "--project", path],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual([item["id"] for item in json.loads(result.stdout)], ["INI-001"], result.stderr)


ARCHIVED_OLD = """# Actions — Old

## Open
- [ ] **GAM-022** — Jane — Ouverte dans l'archive 📅 2026-01-01
- [x] **GAM-021** — Jane — Mal rangée ✅ 2026-01-06
    - source: s

## Done
- [x] **GAM-020** — Jane — Ancienne ✅ 2026-01-05
    - source: s
    - 05/01: fait

## Cancelled
"""

ARCHIVED_TOOL = """# Actions — Tool

## Open

## Done
- [x] **TOO-001** — Jane — Outil ✅ 2026-01-05
    - source: s
"""


class ActionArchivedProjectTest(unittest.TestCase):
    """An archived project (a folder moved whole to an `archive/` folder, at the level of what it holds) is out of the context:
    read-only, left out of the listings. The subclasses below run every test again on the other archive places."""

    ROOT = "projects/clients/acme/missions/archive/old"  # what `unarchive` brings back: the outermost archived folder
    OLD = "projects/clients/acme/missions/archive/old/state/actions.md"
    TOOL = "projects/internal/archive/tool/state/actions.md"
    act = ActionCommandTest.act
    text = ActionCommandTest.text
    create = ActionCommandTest.create

    @property
    def UNARCHIVE(self) -> str:
        return f"unarchive it first with `uv run tools/brain/brain-state.py unarchive brain/{self.ROOT} --write`"

    def setUp(self) -> None:
        ActionCommandTest.setUp(self)
        self.brain = self.brain.resolve()
        self.old = self.brain / self.OLD
        self.tool = self.brain / self.TOOL
        for path, content in ((self.old, ARCHIVED_OLD), (self.tool, ARCHIVED_TOOL)):
            path.parent.mkdir(parents=True)
            path.write_text(content, encoding="utf-8")

    def tearDown(self) -> None:
        ActionCommandTest.tearDown(self)

    def tree(self) -> dict:
        return {str(path.relative_to(self.brain)): path.read_bytes() for path in self.brain.rglob("*") if path.is_file()}

    def refused(self, *args: str) -> dict:
        before = self.tree()
        error = self.act(*args, code=2)
        self.assertEqual(error["kind"], "bad_request")
        self.assertIn("is archived", error["error"])
        self.assertIn("unarchive it first", error["error"])
        self.assertEqual(self.tree(), before)
        return error

    def test_list_leaves_archived_projects_out_and_archived_brings_them_back_flagged(self) -> None:
        self.assertEqual([item["id"] for item in self.act("list", "--state", "all")], ["GAM-001"])
        listed = self.act("list", "--state", "all", "--archived")
        self.assertEqual(sorted(item["id"] for item in listed), ["GAM-001", "GAM-020", "GAM-021", "GAM-022", "TOO-001"])
        flags = {item["id"]: item.get("project_archived") for item in listed}
        self.assertEqual(flags, {"GAM-001": None, "GAM-020": True, "GAM-021": True, "GAM-022": True, "TOO-001": True})
        self.assertIn("[ ] GAM-022 — Jane — Ouverte dans l'archive 📅 2026-01-01  (acme / old, archived)", self.act("list", "--archived", "--table"))
        self.assertIn("[ ] GAM-001 — Jane — Existante 📅 2026-10-20  (acme / gamma)\n", self.act("list", "--archived", "--table"))
        self.assertNotIn("archived", self.act("list", "--table"))

    def test_list_project_names_an_archived_project_only_with_archived(self) -> None:
        error = self.act("list", "--project", "acme/old", code=2)
        self.assertEqual(error["kind"], "bad_request")
        self.assertIn("is archived", error["error"])
        self.assertIn("add --archived to read it", error["error"])
        self.assertIn("unarchive", error["error"])
        self.assertEqual([item["id"] for item in self.act("list", "--project", "acme/old", "--archived", "--state", "all")], ["GAM-022", "GAM-021", "GAM-020"])
        self.assertTrue(all(item["project_archived"] for item in self.act("list", "--project", "tool", "--archived", "--state", "all")))
        self.assertEqual([item["id"] for item in self.act("list", "--project", "acme/gamma", "--archived")], ["GAM-001"])  # a live one, as ever

    def test_writes_on_an_archived_project_are_refused_and_change_nothing(self) -> None:
        self.assertIn(self.UNARCHIVE, self.refused("create", "--project", "acme/old", "--title", "x", "--owner", "Jane", "--source", "s")["error"])
        self.refused("create", "--project", "tool", "--title", "x", "--owner", "Jane", "--source", "s")
        self.refused("create", "--project", "acme/old", "--title", "x", "--owner", "Jane", "--source", "s", "--dry-run")
        self.assertIn(self.UNARCHIVE, self.refused("update", "GAM-020", "--title", "x")["error"])
        self.refused("update", "GAM-020", "--state", " ")
        self.refused("update", "TOO-001", "--title", "x", "--dry-run")
        self.refused("history", "add", "GAM-020", "--text", "note")
        self.refused("history", "edit", "GAM-020", "--index", "1", "--text", "autre")
        self.refused("history", "remove", "GAM-020", "--index", "1")
        self.refused("subtask", "add", "GAM-020", "--text", "étape")
        self.refused("subtask", "toggle", "GAM-020", "--index", "0")
        self.refused("subtask", "edit", "GAM-020", "--index", "0", "--text", "autre")
        self.refused("subtask", "remove", "GAM-020", "--index", "0")
        self.refused("move", "GAM-020", "--to", "acme/gamma")  # from an archived register
        self.refused("move", "GAM-001", "--to", "acme/old")  # to an archived register
        self.refused("delete", "GAM-020")
        self.assertEqual(self.old.read_text(encoding="utf-8"), ARCHIVED_OLD)
        self.assertEqual(self.text(), REGISTER)

    def test_show_still_reads_an_action_of_an_archived_project(self) -> None:
        shown = self.act("show", "GAM-020")
        self.assertEqual((shown["state"], shown["project"], shown["register"], shown["project_archived"]),
                         ("x", "acme / old", self.OLD, True))
        self.assertTrue(self.act("show", "TOO-001")["project_archived"])
        self.assertNotIn("project_archived", self.act("show", "GAM-001"))
        text = self.act("show", "GAM-020", "--text")
        self.assertEqual(text.splitlines()[-1], f"{self.old}:9 (archived project)")
        self.assertIn("acme / old · closed 2026-01-05", text)
        self.assertNotIn("archived project", self.act("show", "GAM-001", "--text"))

    def test_a_new_action_counts_the_ids_of_an_archived_mission_of_the_client(self) -> None:
        created = self.create()  # GAM-001 is live, GAM-022 is the highest of the archived mission: never reused
        self.assertEqual(created["id"], "GAM-023")
        self.assertEqual(self.act("show", "GAM-023")["project"], "acme / gamma")

    def test_check_skips_the_format_of_archived_registers_but_their_ids_still_count(self) -> None:
        self.old.write_text(ARCHIVED_OLD.replace("## Cancelled\n", "## Cancelled\n- [?] **GAM-023** — Jane — État inconnu\n"), encoding="utf-8")
        self.assertIn("0 error(s), 0 warning(s)", self.act("check"))
        out = self.act("check", "--archived", code=1)
        self.assertIn("malformed action line", out)
        self.assertIn("GAM-022 without a source sub-bullet", out)
        self.assertIn("1 error(s)", out)
        named = self.act("check", "--register", str(self.old), code=1)  # a register named is checked, archived or not
        self.assertIn("malformed action line", named)
        self.assertIn("0 error(s), 0 warning(s)", self.act("check", "--register", str(self.register)))
        self.old.write_text(ARCHIVED_OLD, encoding="utf-8")
        # a live action reusing an archived ID is an error, even though the archived register is not format-checked
        self.register.write_text(REGISTER.replace("## Done\n", "## Done\n- [x] **GAM-020** — Jane — Reprise ✅ 2026-10-01\n    - source: s\n"), encoding="utf-8")
        out = self.act("check", code=1)
        self.assertRegex(out, r"GAM-020 already present \(")  # reported on whichever of the two registers sorts second
        self.assertIn("1 error(s)", out)
        self.assertIn(f"{self.OLD}:9", out)
        self.assertNotIn("without a source", out)
        self.assertEqual(self.act("show", "GAM-020", code=4)["kind"], "conflict")

    def test_sweep_and_archive_skip_archived_projects(self) -> None:
        def maintain(*args: str) -> str:
            result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), *args, "--today", "2026-10-13"],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        # GAM-021 is a closure misfiled under Open and GAM-020 is far older than 60 days: a live register moves both
        for command in ("sweep", "archive"):
            self.assertIn("0 action(s) moved in 0 register(s)", maintain(command, "--write"))
            self.assertEqual(self.old.read_text(encoding="utf-8"), ARCHIVED_OLD)
            self.assertEqual(sorted(path.name for path in self.old.parent.iterdir()), ["actions.md"])
            self.assertEqual(sorted(path.name for path in self.tool.parent.iterdir()), ["actions.md"])
        self.assertEqual(maintain("sweep", "--register", str(self.old)).splitlines()[0], f"{self.old}: skipped, archived project")
        self.assertIn("skipped, archived project", maintain("archive", "--register", str(self.old), "--write"))
        self.assertEqual(self.old.read_text(encoding="utf-8"), ARCHIVED_OLD)
        # the same register, live, is moved
        live = self.brain / "projects/clients/acme/missions/old/state/actions.md"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text(ARCHIVED_OLD.replace("GAM-02", "OLD-02"), encoding="utf-8")
        self.assertIn("sweep OLD-021 open → done", maintain("sweep", "--register", str(live)))
        self.assertIn("archive 1 action(s) → actions-archive-2026.md (OLD-020)", maintain("archive", "--register", str(live)))

    def test_a_new_internal_action_counts_the_ids_of_the_three_places_of_the_project(self) -> None:
        live = self.brain / "projects/internal/tool"
        (live / "state").mkdir(parents=True)
        (live / "state/actions.md").write_text("# Actions — Tool\n\n## Open\n\n## Done\n- [x] **TOO-001** — Jane — Outil ✅ 2026-01-05\n    - source: s\n", encoding="utf-8")
        args = ("create", "--project", "internal/tool", "--title", "x", "--owner", "Jane", "--source", "s")
        for place, number in (("projects/internal/archive/tool", 4), ("projects/archive/tool", 9)):
            (self.brain / place).mkdir(parents=True, exist_ok=True)
            (self.brain / place / "notes.md").write_text(f"Mentions TOO-{number:03d}\n", encoding="utf-8")
        self.assertEqual(self.act(*args)["id"], "TOO-010")  # the highest of the live folder and of both archive places
        (self.brain / "projects/archive/tool/notes.md").unlink()
        self.assertEqual(self.act(*args)["id"], "TOO-011")  # the live register now holds TOO-010, above the other place's TOO-004

    def test_a_live_internal_action_cannot_reuse_an_id_of_an_archived_place(self) -> None:
        live = self.brain / "projects/internal/tool"
        (live / "state").mkdir(parents=True)
        (live / "state/actions.md").write_text("# Actions — Tool\n\n## Open\n\n## Done\n- [x] **TOO-001** — Jane — Reprise ✅ 2026-01-05\n    - source: s\n", encoding="utf-8")
        out = self.act("check", code=1)
        self.assertIn(f"TOO-001 already present ({self.TOOL}:", out)


class ActionEarlierPlacesTest(ActionArchivedProjectTest):
    """The same behaviour for the earlier archive places, which still count as archived: `archive/<project>`, `clients/<client>/archive/<mission>`."""

    ROOT = "projects/clients/acme/archive/old"
    OLD = "projects/clients/acme/archive/old/state/actions.md"
    TOOL = "projects/archive/tool/state/actions.md"


class ActionArchivedClientTest(ActionArchivedProjectTest):
    """A whole client archived (`clients/archive/<client>/`, all its missions) next to a live folder of the same name: the same behaviour."""

    ROOT = "projects/clients/archive/acme"
    OLD = "projects/clients/archive/acme/missions/old/state/actions.md"

    def test_the_label_of_a_register_of_an_archived_client_reads_like_a_live_one(self) -> None:
        self.assertEqual(self.act("show", "GAM-020")["project"], "acme / old")
        self.assertIn("acme / old, archived)", self.act("list", "--archived", "--table"))

    def test_a_new_action_never_reuses_the_ids_of_the_archived_client(self) -> None:
        self.assertEqual(self.create()["id"], "GAM-023")  # GAM-022 sits in clients/archive/acme


if __name__ == "__main__":
    unittest.main()


REGISTER = """# Actions — Gamma

## Open
- [ ] **GAM-001** — Jane — Existante 📅 2026-10-20
    - source: s

## Done

## Cancelled
"""
