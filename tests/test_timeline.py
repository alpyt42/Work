"""Regression checks for the timeline tool: entries at their date and the monthly roll into journal/ (no network, temporary brain)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/brain/timeline.py"

ROLLOUT = """# Mission: Rollout

- **Status:** active

## Context
Background in [context](workstreams/context.md).

## Timeline
Previous months: [2026-09](journal/2026-09.md)

- 2026-10-14 — Demo recorded, see [minutes](sources/2026-10/2026-10-14-cr-demo.md) (Sonnet 5)
- 2026-10-14 — Kickoff held (Opus 5.5)
- 2026-10-02 — Scope agreed with [Jane Doe](../../../../people/jane-doe.md) (Opus 5.5)

## Links
- [Sources](sources/2026-10/index.md)
"""

JOURNAL_SEPTEMBER = """# Journal — Rollout — 2026-09

[Back to project](../rollout.md)

> Journal archive of Rollout for September 2026: entries moved from the project page on 2026-10-01. The current month stays on the page.

- 2026-09-28 — Contract signed (Opus 5.5)
- 2026-09-10 — Workshop held, see [notes](../notes/2026-09-10-workshop.md) (Opus 5.5)
"""

SETUP = """# Project: Setup

## Context
Tooling.

## Timeline

- 2026-10-15 — Hooks installed (Opus 5.5)
- 2026-09-30 — Skills linked, see [guide](notes/2026-09-30-skills.md) (Opus 5.5)
"""

GLOBEX = """# Client: Globex

## Missions
- [Rollout](missions/rollout/rollout.md)

## Timeline
- 2026-10-03 — Account review, see [minutes](missions/rollout/sources/2026-10/2026-10-03-cr-review.md) (Opus 5.5)
- 2026-09-12 — Contract renewed (Opus 5.5)

## Contacts
- [Jane Doe](../../people/jane-doe.md)
"""

ACTIONS = "# Actions — {name}\n\n## Open\n\n## Done\n\n## Cancelled\n"


class TimelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain-acme"
        self.mission = self.brain / "projects/clients/globex/missions/rollout"
        self.setup_dir = self.brain / "projects/internal/setup"
        self.client = self.brain / "projects/clients/globex"
        for folder, page, text in ((self.mission, "rollout.md", ROLLOUT), (self.setup_dir, "setup.md", SETUP)):
            (folder / "state").mkdir(parents=True)
            (folder / "state/actions.md").write_text(ACTIONS.format(name=folder.name), encoding="utf-8")
            (folder / page).write_text(text, encoding="utf-8")
        (self.client / "globex.md").write_text(GLOBEX, encoding="utf-8")
        (self.mission / "journal").mkdir()
        (self.mission / "journal/2026-09.md").write_text(JOURNAL_SEPTEMBER, encoding="utf-8")
        self.page = self.mission / "rollout.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_tool(self, *args: str, code: int = 0, now: str = "2026-10-20 10:00") -> dict | str:
        env = {**os.environ, "ACTION_NOW": now}
        result = subprocess.run([sys.executable, str(TOOL), "--brain", str(self.brain), *args], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        try:
            return json.loads(result.stdout)
        except ValueError:
            return result.stderr

    def add(self, text: str, *extra: str, project: str = "globex/rollout", now: str = "2026-10-20 10:00", code: int = 0) -> dict | str:
        return self.run_tool("add", "--project", project, "--model", "Sonnet 5", *extra, text, now=now, code=code)

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    @staticmethod
    def outside_timeline(text: str) -> str:
        head, rest = text.split("## Timeline")
        return head + (rest[rest.find("\n## "):] if "\n## " in rest else "")

    def snapshot(self) -> dict[str, str]:
        return {p.relative_to(self.brain).as_posix(): p.read_text(encoding="utf-8") for p in sorted(self.brain.rglob("*.md"))}

    # --- add ---

    def test_add_today_goes_on_top_of_the_current_month(self) -> None:
        result = self.add("Wrote the plan")
        self.assertEqual(result["entry"], "- 2026-10-20 — Wrote the plan (Sonnet 5)")
        self.assertEqual((result["file"], result["journal"], result["rolled"]["moved"]), ("projects/clients/globex/missions/rollout/rollout.md", False, 0))
        expected = ROLLOUT.replace(
            "\n- 2026-10-14 — Demo", "\n- 2026-10-20 — Wrote the plan (Sonnet 5)\n- 2026-10-14 — Demo", 1)
        self.assertEqual(self.read(self.page), expected)

    def test_add_defaults_to_the_current_date(self) -> None:
        self.assertEqual(self.add("Late evening", now="2026-10-31 23:30")["date"], "2026-10-31")
        self.assertEqual(self.add("Just after midnight", now="2026-11-01 00:10")["date"], "2026-11-01")

    def test_add_on_a_date_goes_above_the_same_date_and_below_newer_entries(self) -> None:
        self.add("Same day as the demo", "--date", "2026-10-14")
        self.add("Between the kickoff and the scope", "--date", "2026-10-10")
        self.add("Newest", "--date", "2026-10-19")
        entries = [line for line in self.read(self.page).splitlines() if line.startswith("- 2026-")]
        self.assertEqual([line[2:12] for line in entries], ["2026-10-19", "2026-10-14", "2026-10-14", "2026-10-14", "2026-10-10", "2026-10-02"])
        self.assertIn("Same day as the demo", entries[1])
        self.assertIn("Demo recorded", entries[2])
        self.assertIn("Between the kickoff", entries[4])

    def test_add_in_a_past_month_goes_into_the_existing_journal(self) -> None:
        before = self.read(self.page)
        result = self.add("Late event, see [minutes](sources/2026-09/2026-09-20-cr-late.md)", "--date", "2026-09-20")
        self.assertEqual((result["journal"], result["created_file"]), (True, False))
        self.assertEqual(result["file"], "projects/clients/globex/missions/rollout/journal/2026-09.md")
        self.assertEqual(self.read(self.mission / "journal/2026-09.md"), JOURNAL_SEPTEMBER.replace(
            "- 2026-09-10 —",
            "- 2026-09-20 — Late event, see [minutes](../sources/2026-09/2026-09-20-cr-late.md) (Sonnet 5)\n- 2026-09-10 —"))
        self.assertEqual(self.read(self.page), before)  # the month was already listed

    def test_add_in_a_past_month_creates_the_journal_and_lists_it(self) -> None:
        result = self.add("Pre-sales call", "--date", "2026-08-30")
        self.assertTrue(result["created_file"])
        self.assertEqual(self.read(self.mission / "journal/2026-08.md"), (
            "# Journal — Rollout — 2026-08\n\n[Back to project](../rollout.md)\n\n"
            "> Journal archive of Rollout for August 2026: entries moved from the project page on 2026-10-20. The current month stays on the page.\n\n"
            "- 2026-08-30 — Pre-sales call (Sonnet 5)\n"))
        self.assertIn("\nPrevious months: [2026-09](journal/2026-09.md) · [2026-08](journal/2026-08.md)\n", self.read(self.page))

    def test_add_in_a_new_month_rolls_the_older_entries_first(self) -> None:
        result = self.add("Planned the sprint", now="2026-11-02 09:00")
        self.assertEqual(result["rolled"]["moved"], 3)
        self.assertEqual([(m["month"], m["count"], m["created"]) for m in result["rolled"]["months"]], [("2026-10", 3, True)])
        self.assertEqual(self.read(self.page), ROLLOUT.replace(
            "Previous months: [2026-09](journal/2026-09.md)\n\n"
            "- 2026-10-14 — Demo recorded, see [minutes](sources/2026-10/2026-10-14-cr-demo.md) (Sonnet 5)\n"
            "- 2026-10-14 — Kickoff held (Opus 5.5)\n"
            "- 2026-10-02 — Scope agreed with [Jane Doe](../../../../people/jane-doe.md) (Opus 5.5)\n",
            "Previous months: [2026-10](journal/2026-10.md) · [2026-09](journal/2026-09.md)\n\n"
            "- 2026-11-02 — Planned the sprint (Sonnet 5)\n"))
        self.assertEqual(self.read(self.mission / "journal/2026-10.md"), (
            "# Journal — Rollout — 2026-10\n\n[Back to project](../rollout.md)\n\n"
            "> Journal archive of Rollout for October 2026: entries moved from the project page on 2026-11-02. The current month stays on the page.\n\n"
            "- 2026-10-14 — Demo recorded, see [minutes](../sources/2026-10/2026-10-14-cr-demo.md) (Sonnet 5)\n"
            "- 2026-10-14 — Kickoff held (Opus 5.5)\n"
            "- 2026-10-02 — Scope agreed with [Jane Doe](../../../../../people/jane-doe.md) (Opus 5.5)\n"))

    def test_add_dry_run_writes_nothing(self) -> None:
        before = self.snapshot()
        result = self.add("Planned the sprint", "--dry-run", now="2026-11-02 09:00")
        self.assertEqual((result["dry_run"], result["rolled"]["moved"]), (True, 3))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.mission / "journal/2026-10.md").exists())

    def test_add_a_future_month_stays_on_the_page(self) -> None:
        result = self.add("Planned go-live", "--date", "2026-11-15")
        self.assertEqual((result["journal"], result["rolled"]["moved"]), (False, 0))
        self.assertIn("## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n\n- 2026-11-15 — Planned go-live (Sonnet 5)\n- 2026-10-14", self.read(self.page))

    def test_add_validates_its_input(self) -> None:
        for args in (("--date", "2026-13-40"), ("--date", "20/10/2026")):
            self.assertEqual(self.add("Text", *args, code=2)["kind"], "bad_request")
        self.assertEqual(self.add("   ", code=2)["kind"], "bad_request")
        self.assertEqual(self.add("two\nlines", code=2)["kind"], "bad_request")
        self.assertEqual(self.add("x" * 2001, code=2)["kind"], "bad_request")
        self.assertIn("--model", self.run_tool("add", "--project", "globex/rollout", "text", code=2))
        self.assertEqual(self.read(self.page), ROLLOUT)

    def test_add_on_a_project_without_timeline_creates_the_section(self) -> None:
        (self.setup_dir / "setup.md").write_text("# Project: Setup\n\n## Context\nTooling.\n", encoding="utf-8")
        self.add("First entry", project="setup")
        self.assertEqual(self.read(self.setup_dir / "setup.md"), "# Project: Setup\n\n## Context\nTooling.\n\n## Timeline\n\n- 2026-10-20 — First entry (Sonnet 5)\n")

    def test_add_replaces_the_seed_placeholder(self) -> None:
        (self.setup_dir / "setup.md").write_text("# Project: Setup\n\n## Timeline\n\n- (no entries yet)\n", encoding="utf-8")
        self.add("First entry", project="setup")
        self.assertEqual(self.read(self.setup_dir / "setup.md"), "# Project: Setup\n\n## Timeline\n\n- 2026-10-20 — First entry (Sonnet 5)\n")

    def test_add_in_an_empty_timeline_followed_by_a_section(self) -> None:
        (self.setup_dir / "setup.md").write_text("# Project: Setup\n\n## Timeline\n\n## Links\n- x\n", encoding="utf-8")
        self.add("First entry", project="setup")
        self.assertEqual(self.read(self.setup_dir / "setup.md"), "# Project: Setup\n\n## Timeline\n\n- 2026-10-20 — First entry (Sonnet 5)\n\n## Links\n- x\n")

    # --- roll ---

    def test_roll_is_a_dry_run_unless_written(self) -> None:
        before = self.snapshot()
        report = self.run_tool("roll", now="2026-11-02 09:00")
        self.assertEqual((report["dry_run"], report["total"], report["checked"]), (True, 7, 3))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_tool("roll", "--dry-run", now="2026-11-02 09:00")["total"], report["total"])
        written = self.run_tool("roll", "--write", now="2026-11-02 09:00")
        self.assertEqual((written["dry_run"], written["total"]), (False, report["total"]))
        self.assertNotEqual(self.snapshot(), before)
        self.assertTrue((self.mission / "journal/2026-10.md").is_file())

    def test_roll_twice_changes_nothing(self) -> None:
        self.run_tool("roll", "--write", now="2026-11-02 09:00")
        after = self.snapshot()
        again = self.run_tool("roll", "--write", now="2026-11-02 09:00")
        self.assertEqual((again["total"], again["projects"]), (0, []))
        self.assertEqual(self.snapshot(), after)

    def test_roll_only_moves_the_months_before_the_current_one(self) -> None:
        report = self.run_tool("roll", "--write")  # 2026-10-20: the September entries of the setup and client pages
        self.assertEqual(sorted((p["project"], p["moved"]) for p in report["projects"]), [("clients/globex", 1), ("setup", 1)])
        self.assertEqual(self.read(self.page), ROLLOUT)

    def test_roll_one_project_only(self) -> None:
        report = self.run_tool("roll", "--project", "setup", "--write", now="2026-11-02 09:00")
        self.assertEqual([(p["project"], p["moved"]) for p in report["projects"]], [("setup", 2)])
        self.assertEqual(self.read(self.page), ROLLOUT)
        self.assertEqual(self.read(self.setup_dir / "journal/2026-10.md"), (
            "# Journal — Setup — 2026-10\n\n[Back to project](../setup.md)\n\n"
            "> Journal archive of Setup for October 2026: entries moved from the project page on 2026-11-02. The current month stays on the page.\n\n"
            "- 2026-10-15 — Hooks installed (Opus 5.5)\n"))

    def test_roll_merges_into_an_existing_journal_without_duplicates(self) -> None:
        late = ("- 2026-09-20 — Late event, see [minutes](sources/2026-09/2026-09-20-cr-late.md) (Opus 5.5)\n"
                "- 2026-09-10 — Workshop held, see [notes](notes/2026-09-10-workshop.md) (Opus 5.5)\n")
        self.page.write_text(ROLLOUT.replace("- 2026-10-14 — Demo", late + "- 2026-10-14 — Demo", 1), encoding="utf-8")
        report = self.run_tool("roll", "--project", "globex/rollout", "--write")
        self.assertEqual([(m["month"], m["count"], m["duplicates"], m["created"]) for m in report["projects"][0]["months"]], [("2026-09", 2, 1, False)])
        self.assertEqual(self.read(self.mission / "journal/2026-09.md"), JOURNAL_SEPTEMBER.replace(
            "- 2026-09-10 —",
            "- 2026-09-20 — Late event, see [minutes](../sources/2026-09/2026-09-20-cr-late.md) (Opus 5.5)\n- 2026-09-10 —"))
        self.assertEqual(self.read(self.page), ROLLOUT)

    def test_roll_keeps_the_order_of_moved_entries_of_the_same_day(self) -> None:
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        journal = [line for line in self.read(self.mission / "journal/2026-10.md").splitlines() if line.startswith("- ")]
        self.assertTrue(journal[0].startswith("- 2026-10-14 — Demo recorded"))
        self.assertTrue(journal[1].startswith("- 2026-10-14 — Kickoff"))

    def test_roll_corrects_relative_links_only(self) -> None:
        entry = ("- 2026-09-05 — Links: [a](sources/a.md) [b](./b.md) [c](../c.md) [url](https://example.com/x) [mail](mailto:jane@example.com) "
                 "[top](#timeline) [abs](/etc/x.md) [spaced](<notes/my note.md>) ![img](assets/p.png) [titled](notes/t.md \"A title\") `[code](kept.md)` (Opus 5.5)")
        (self.setup_dir / "setup.md").write_text(f"# Project: Setup\n\n## Timeline\n{entry}\n", encoding="utf-8")
        self.run_tool("roll", "--project", "setup", "--write")
        moved = [line for line in self.read(self.setup_dir / "journal/2026-09.md").splitlines() if line.startswith("- ")][0]
        self.assertEqual(moved, (
            "- 2026-09-05 — Links: [a](../sources/a.md) [b](../b.md) [c](../../c.md) [url](https://example.com/x) [mail](mailto:jane@example.com) "
            "[top](#timeline) [abs](/etc/x.md) [spaced](<../notes/my note.md>) ![img](../assets/p.png) [titled](../notes/t.md \"A title\") `[code](kept.md)` (Opus 5.5)"))

    def test_roll_moves_the_continuation_lines_with_their_entry(self) -> None:
        (self.setup_dir / "setup.md").write_text(
            "# Project: Setup\n\n## Timeline\n- 2026-10-15 — Current (m)\n- 2026-09-05 — Old (m)\n    - detail with [link](notes/x.md)\n- 2026-09-01 — Older (m)\n", encoding="utf-8")
        self.run_tool("roll", "--project", "setup", "--write")
        self.assertIn("- 2026-09-05 — Old (m)\n    - detail with [link](../notes/x.md)\n- 2026-09-01 — Older (m)\n", self.read(self.setup_dir / "journal/2026-09.md"))
        self.assertEqual(self.read(self.setup_dir / "setup.md"),
                         "# Project: Setup\n\n## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n\n- 2026-10-15 — Current (m)\n")

    def test_roll_creates_the_previous_months_line_under_the_heading(self) -> None:
        self.run_tool("roll", "--project", "setup", "--write")
        self.assertEqual(self.read(self.setup_dir / "setup.md"),
                         SETUP.replace("## Timeline\n\n- 2026-10-15 — Hooks installed (Opus 5.5)\n- 2026-09-30 — Skills linked, see [guide](notes/2026-09-30-skills.md) (Opus 5.5)\n",
                                       "## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n\n- 2026-10-15 — Hooks installed (Opus 5.5)\n"))
        self.assertIn("- 2026-09-30 — Skills linked, see [guide](../notes/2026-09-30-skills.md) (Opus 5.5)\n", self.read(self.setup_dir / "journal/2026-09.md"))

    def test_roll_updates_the_previous_months_line_most_recent_first(self) -> None:
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        self.assertIn("\nPrevious months: [2026-10](journal/2026-10.md) · [2026-09](journal/2026-09.md)\n", self.read(self.page))
        self.add("December", now="2026-12-03 09:00")
        # the page holds no entry of a past month: the line is already right and the new entry is the only one
        self.assertIn("\nPrevious months: [2026-10](journal/2026-10.md) · [2026-09](journal/2026-09.md)\n\n- 2026-12-03 — December (Sonnet 5)\n", self.read(self.page))

    def test_roll_replaces_the_template_placeholder_line(self) -> None:
        (self.setup_dir / "setup.md").write_text(
            "# Project: Setup\n\n## Timeline\n> Only the current month stays here.\nPrevious months: [YYYY-MM](journal/YYYY-MM.md)\n- 2026-10-15 — Current (m)\n- 2026-09-05 — Old (m)\n", encoding="utf-8")
        self.run_tool("roll", "--project", "setup", "--write")
        self.assertEqual(self.read(self.setup_dir / "setup.md"),
                         "# Project: Setup\n\n## Timeline\n> Only the current month stays here.\nPrevious months: [2026-09](journal/2026-09.md)\n- 2026-10-15 — Current (m)\n")

    def test_roll_relocates_a_previous_months_line_found_among_the_entries(self) -> None:
        (self.setup_dir / "setup.md").write_text(
            "# Project: Setup\n\n## Timeline\n\n- 2026-10-15 — A (m)\n- 2026-10-14 — B (m)\nPrevious months: [2026-08](journal/2026-08.md)\n\n- 2026-10-13 — C (m)\n- 2026-09-02 — Old (m)\n", encoding="utf-8")
        self.run_tool("roll", "--project", "setup", "--write")
        self.assertEqual(self.read(self.setup_dir / "setup.md"), (
            "# Project: Setup\n\n## Timeline\nPrevious months: [2026-09](journal/2026-09.md) · [2026-08](journal/2026-08.md)\n\n"
            "- 2026-10-15 — A (m)\n- 2026-10-14 — B (m)\n- 2026-10-13 — C (m)\n"))

    def test_roll_reads_the_french_wording_and_writes_english(self) -> None:
        french_journal = (
            "# Journal — Rollout — 2026-09\n\n[Retour au projet](../rollout.md)\n\n"
            "> Archive du journal de Rollout pour septembre 2026 : entrées déplacées depuis la fiche le 2026-10-01. Les mois en cours restent dans la fiche.\n\n"
            "- 2026-09-28 — Contrat signé (Opus 5.5)\n")
        (self.mission / "journal/2026-09.md").write_text(french_journal, encoding="utf-8")
        self.page.write_text(ROLLOUT.replace("Previous months:", "Mois précédents :"), encoding="utf-8")
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        page = self.read(self.page)
        self.assertIn("\nPrevious months: [2026-10](journal/2026-10.md) · [2026-09](journal/2026-09.md)\n", page)
        self.assertNotIn("Mois précédents", page)
        self.assertEqual(self.read(self.mission / "journal/2026-09.md"), french_journal)  # an existing header is left as it is
        journal = self.read(self.mission / "journal/2026-10.md")
        self.assertTrue(journal.startswith(
            "# Journal — Rollout — 2026-10\n\n[Back to project](../rollout.md)\n\n"
            "> Journal archive of Rollout for October 2026: entries moved from the project page on 2026-11-02. The current month stays on the page.\n\n- 2026-10-14"))

    def test_a_new_journal_follows_the_title_order_of_the_existing_ones(self) -> None:
        (self.mission / "journal/2026-09.md").write_text(
            "# Journal — 2026-09 — Rollout\n\n> Journal archive of Rollout for September 2026: entries moved from the project page on 2026-10-01. The current month stays on the page.\n\n- 2026-09-28 — Contract signed (Opus 5.5)\n", encoding="utf-8")
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        self.assertTrue(self.read(self.mission / "journal/2026-10.md").startswith("# Journal — 2026-10 — Rollout\n\n[Back to project](../rollout.md)\n"))

    def test_a_new_wording_is_english_even_in_a_french_brain(self) -> None:
        (self.mission / "journal/2026-09.md").unlink()
        self.page.write_text(ROLLOUT.replace("Previous months: [2026-09](journal/2026-09.md)\n", ""), encoding="utf-8")
        (self.setup_dir / "setup.md").write_text(SETUP.replace("## Timeline\n", "## Timeline\nMois précédents : [2026-08](journal/2026-08.md)\n"), encoding="utf-8")
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        self.assertIn("\nPrevious months: [2026-10](journal/2026-10.md)\n", self.read(self.page))
        self.assertIn("[Back to project](../rollout.md)", self.read(self.mission / "journal/2026-10.md"))

    def test_only_the_timeline_section_and_the_journals_change(self) -> None:
        before = self.snapshot()
        self.add("Planned the sprint", now="2026-11-02 09:00")
        self.run_tool("roll", "--write", now="2026-11-02 09:00")
        after = self.snapshot()
        changed = {path for path in after if before.get(path) != after[path]}
        self.assertEqual(changed, {"projects/clients/globex/missions/rollout/rollout.md", "projects/clients/globex/missions/rollout/journal/2026-10.md",
                                   "projects/internal/setup/setup.md", "projects/internal/setup/journal/2026-09.md", "projects/internal/setup/journal/2026-10.md",
                                   "projects/clients/globex/globex.md", "projects/clients/globex/journal/2026-09.md", "projects/clients/globex/journal/2026-10.md"})
        for path in ("projects/clients/globex/missions/rollout/rollout.md", "projects/internal/setup/setup.md", "projects/clients/globex/globex.md"):
            self.assertEqual(self.outside_timeline(before[path]), self.outside_timeline(after[path]), path)

    def archived_projects(self) -> list[Path]:
        """One archived project in each of the five places, each with a page that has an entry of an old month: a mission in
        `missions/archive/`, an internal project in `internal/archive/`, a whole client in `clients/archive/`, and the earlier
        places `clients/<client>/archive/<mission>` and `archive/<project>`."""
        found = []
        places = ((self.client / "missions/archive/legacy", "legacy"), (self.brain / "projects/internal/archive/tool", "tool"),
                  (self.brain / "projects/clients/archive/initech/missions/pilot", "pilot"), (self.client / "archive/early", "early"),
                  (self.brain / "projects/archive/old-tool", "old-tool"))
        for folder, name in places:
            (folder / "state").mkdir(parents=True)
            (folder / "state/actions.md").write_text(ACTIONS.format(name=name), encoding="utf-8")
            (folder / f"{name}.md").write_text(f"# Project: {name}\n\n## Timeline\n- 2026-03-01 — Old (m)\n- 2026-10-02 — Recent (m)\n", encoding="utf-8")
            found.append(folder)
        return found

    def test_roll_leaves_archived_projects_alone(self) -> None:
        archived = self.archived_projects()
        pages = {folder: self.read(folder / f"{folder.name}.md") for folder in archived}
        report = self.run_tool("roll", "--write", now="2026-11-02 09:00")
        self.assertNotIn("legacy", json.dumps(report))
        self.assertNotIn("tool", [project["project"] for project in report["projects"]])
        self.assertEqual((report["checked"], report["total"]), (3, 7))  # the live pages only, whichever archive place the others are in
        for folder in archived:
            self.assertFalse((folder / "journal").exists())
            self.assertEqual(self.read(folder / f"{folder.name}.md"), pages[folder])  # the old-month entry stays on the page
        self.assertEqual(self.run_tool("roll", now="2026-11-02 09:00")["total"], 0)

    def test_add_state_and_roll_project_refuse_an_archived_project_and_change_nothing(self) -> None:
        self.archived_projects()
        before = self.snapshot()
        refusals = [self.add("Late entry", project=name, code=2) for name in ("globex/legacy", "tool", "initech/pilot", "globex/early", "old-tool")]
        refusals += [self.add("Late entry", "--dry-run", project="tool", code=2), self.state("Pilot live", project="initech/pilot", code=2),
                    self.add("Late entry", "--date", "2026-03-05", project="globex/legacy", code=2),
                    self.state("Pilot live", project="globex/legacy", code=2), self.state("Pilot live", project="tool", extra=("--dry-run",), code=2),
                    self.run_tool("roll", "--project", "globex/legacy", code=2), self.run_tool("roll", "--project", "tool", "--write", code=2)]
        for error in refusals:
            self.assertEqual(error["kind"], "bad_request")
            self.assertIn("is archived", error["error"])
            self.assertIn("unarchive it first with `uv run tools/brain/brain-state.py unarchive brain-acme/projects/", error["error"])
        self.assertIn("projects/clients/archive/initech --write", refusals[2]["error"])  # the outermost archived folder: the client
        self.assertIn("projects/clients/globex/missions/archive/legacy --write", refusals[0]["error"])
        self.assertIn("projects/internal/archive/tool --write", refusals[1]["error"])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(path.name == "journal" for path in self.brain.rglob("*") if "archive" in path.parts))

    def test_crlf_files_keep_their_line_endings(self) -> None:
        self.page.write_bytes(ROLLOUT.replace("\n", "\r\n").encode("utf-8"))
        self.run_tool("roll", "--project", "globex/rollout", "--write", now="2026-11-02 09:00")
        self.assertNotIn(b"\n", self.page.read_bytes().replace(b"\r\n", b""))
        self.assertIn(b"Previous months: [2026-10](journal/2026-10.md) \xc2\xb7 [2026-09](journal/2026-09.md)\r\n", self.page.read_bytes())

    def test_a_missing_final_newline_is_kept(self) -> None:
        self.page.write_text(ROLLOUT.rstrip("\n"), encoding="utf-8")
        self.add("Planned the sprint")
        self.assertFalse(self.read(self.page).endswith("\n"))
        self.assertIn("- 2026-10-20 — Planned the sprint (Sonnet 5)\n- 2026-10-14", self.read(self.page))

    def test_a_timeline_heading_inside_a_code_block_is_not_the_section(self) -> None:
        text = "# Project: Setup\n\n```\n## Timeline\n- 2026-09-01 — in a code block\n```\n\n## Timeline\n- 2026-10-15 — Current (m)\n"
        (self.setup_dir / "setup.md").write_text(text, encoding="utf-8")
        self.assertEqual(self.run_tool("roll", "--project", "setup", "--write")["total"], 0)
        self.assertEqual(self.read(self.setup_dir / "setup.md"), text)

    # --- projects ---

    def test_unknown_project_and_missing_page(self) -> None:
        self.assertEqual(self.add("Text", project="globex/unknown", code=2)["kind"], "bad_request")
        self.assertEqual(self.add("Text", project="clients/unknown", code=2)["kind"], "bad_request")
        self.assertEqual(self.run_tool("roll", "--project", "nowhere", code=2)["kind"], "bad_request")
        (self.setup_dir / "setup.md").unlink()
        self.assertEqual(self.add("Text", project="setup", code=3)["kind"], "not_found")

    def test_project_forms(self) -> None:
        for project in ("globex/rollout", "clients/globex/missions/rollout", "globex / rollout",
                        "projects/clients/globex/missions/rollout/state/actions.md"):
            self.assertEqual(self.add("Same page", "--dry-run", project=project)["page"], "projects/clients/globex/missions/rollout/rollout.md", project)

    def test_client_index_page(self) -> None:
        report = self.run_tool("roll", "--project", "clients/globex", "--write")
        self.assertEqual([(p["project"], p["moved"]) for p in report["projects"]], [("clients/globex", 1)])
        self.assertEqual(self.read(self.client / "journal/2026-09.md"), (
            "# Journal — Globex — 2026-09\n\n[Back to project](../globex.md)\n\n"
            "> Journal archive of Globex for September 2026: entries moved from the project page on 2026-10-20. The current month stays on the page.\n\n"
            "- 2026-09-12 — Contract renewed (Opus 5.5)\n"))
        self.assertIn("## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n\n- 2026-10-03 —", self.read(self.client / "globex.md"))
        result = self.add("Account call", project="clients/globex")
        self.assertEqual(result["page"], "projects/clients/globex/globex.md")
        self.assertIn("## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n\n- 2026-10-20 — Account call (Sonnet 5)\n- 2026-10-03 —", self.read(self.client / "globex.md"))
        self.assertTrue(self.read(self.client / "globex.md").startswith(GLOBEX.split("## Timeline")[0]))

    # --- word caps and state ---

    def test_entry_cap_accepts_40_words_and_refuses_41(self) -> None:
        self.assertEqual(self.add(" ".join(["word"] * 40))["dry_run"], False)
        before = self.snapshot()
        message = self.add(" ".join(["word"] * 41), code=2)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("41 words", message["error"])
        self.assertIn("40", message["error"])
        self.assertEqual(message["kind"], "bad_request")

    def test_entry_cap_counts_links_by_label(self) -> None:
        link = "[" + "minutes of the demo" + "](sources/2026-10/2026-10-14-cr-demo-with-a-very-long-slug.md)"
        self.add(" ".join(["word"] * 36) + " " + link)  # 36 + 4 label words
        self.add(" ".join(["word"] * 37) + " " + link, code=2)  # 41

    def test_entry_cap_refuses_in_dry_run(self) -> None:
        before = self.snapshot()
        self.add(" ".join(["word"] * 41), "--dry-run", code=2)
        self.assertEqual(self.add("Ten words are fine here", "--dry-run")["dry_run"], True)
        self.assertEqual(self.snapshot(), before)

    def state(self, *texts: str, project: str = "globex/rollout", code: int = 0, extra: tuple[str, ...] = ()) -> dict | str:
        return self.run_tool("state", "--project", project, "--model", "Sonnet 5", *extra, *texts, code=code)

    def test_state_creates_the_section_after_the_summary(self) -> None:
        page = self.mission / "rollout.md"
        page.write_text(ROLLOUT.replace("## Context\nBackground in [context](workstreams/context.md).\n", "## Summary\n- Scope and deadline.\n\n## Context\nBackground.\n"), encoding="utf-8")
        before = self.read(page)
        result = self.state("Pilot live", "Next step: [plan](notes/plan.md)")
        self.assertEqual((result["created_section"], result["heading"], result["bullets"], result["words"]), (True, "Current state", 2, 5))
        self.assertEqual(result["previous"], [])
        after = self.read(page)
        self.assertIn("- Scope and deadline.\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- Pilot live\n- Next step: [plan](notes/plan.md)\n\n## Context\n", after)
        self.assertEqual(after.replace(after[after.index("## Current state"):after.index("## Context")], ""), before)

    def test_state_creates_the_section_before_read_as_needed_or_timeline(self) -> None:
        self.state("Alpha")
        self.assertIn("\n- **Status:** active\n\n## Context", self.read(self.page))
        self.assertIn("Background in [context](workstreams/context.md).\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- Alpha\n\n## Timeline\n", self.read(self.page))
        page = self.mission / "rollout.md"
        page.write_text(ROLLOUT.replace("## Timeline", "## Read as needed\n- [a](a.md)\n\n## Timeline"), encoding="utf-8")
        self.state("Alpha")
        self.assertIn("\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- Alpha\n\n## Read as needed\n", self.read(page))

    def test_state_creates_the_section_at_the_end_of_a_bare_page(self) -> None:
        page = self.setup_dir / "setup.md"
        page.write_text("# Project: Setup\n\nTooling.\n", encoding="utf-8")
        self.state("Alpha", project="setup")
        self.assertEqual(self.read(page), "# Project: Setup\n\nTooling.\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- Alpha\n")

    def test_state_replaces_an_existing_block_and_keeps_the_rest(self) -> None:
        page = self.mission / "rollout.md"
        page.write_text(ROLLOUT.replace("## Timeline", "## Current state\n\n> As of 2026-09-01 (Old).\n\n- Old one\n- Old two\n\n## Timeline"), encoding="utf-8")
        before = self.read(page)
        old = ["> As of 2026-09-01 (Old).", "", "- Old one", "- Old two"]
        self.assertEqual(self.state("Peek", extra=("--dry-run",))["previous"], old)
        self.assertEqual(self.read(page), before)
        result = self.state("New one", "New two", "New three", extra=("--date", "2026-10-18"))
        self.assertEqual((result["created_section"], result["date"]), (False, "2026-10-18"))
        self.assertEqual(result["previous"], ["> As of 2026-09-01 (Old).", "", "- Old one", "- Old two"])
        self.assertEqual(dry["previous"], ["> As of 2026-10-18 (Sonnet 5).", "", "- New one", "- New two", "- New three"]) if False else None
        after = self.read(page)
        self.assertIn("## Current state\n\n> As of 2026-10-18 (Sonnet 5).\n\n- New one\n- New two\n- New three\n\n## Timeline", after)
        self.assertNotIn("Old", after)
        self.assertEqual(after.replace("> As of 2026-10-18 (Sonnet 5).\n\n- New one\n- New two\n- New three", "X"), before.replace("> As of 2026-09-01 (Old).\n\n- Old one\n- Old two", "X"))
        self.state("Again")
        self.assertEqual(self.read(page).count("## Current state"), 1)

    def test_state_reads_french_headings_and_writes_english(self) -> None:
        page = self.mission / "rollout.md"
        page.write_text("# Mission : Rollout\n\n## État actuel\n\n> État au 2026-09-01 (Old).\n\n- ancien\n\n## Timeline\n", encoding="utf-8")
        result = self.state("nouveau")
        self.assertEqual((result["heading"], result["created_section"]), ("Current state", False))
        self.assertEqual(result["previous"], ["> État au 2026-09-01 (Old).", "", "- ancien"])
        self.assertEqual(self.read(page), "# Mission : Rollout\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- nouveau\n\n## Timeline\n")
        page.write_text("# Mission : Rollout\n\n## En bref\n- résumé\n\n## Lire selon le besoin\n- x\n", encoding="utf-8")
        self.assertEqual(self.state("nouveau")["heading"], "Current state")
        self.assertIn("- résumé\n\n## Current state\n\n> As of 2026-10-20 (Sonnet 5).\n\n- nouveau\n\n## Lire selon", self.read(page))

    def test_state_refuses_too_many_words_or_bullets(self) -> None:
        before = self.snapshot()
        self.assertIn("151 words", self.state(" ".join(["w"] * 76), " ".join(["w"] * 75), code=2)["error"])
        self.assertEqual(self.state(" ".join(["w"] * 75), " ".join(["w"] * 75))["words"], 150)
        before = self.snapshot()
        self.assertIn("7 bullets", self.state(*["x"] * 7, code=2)["error"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.state(*["x"] * 6)["bullets"], 6)

    def test_state_dry_run_writes_nothing(self) -> None:
        before = self.snapshot()
        result = self.state("one", "two", extra=("--dry-run",))
        self.assertEqual((result["dry_run"], result["created_section"], result["previous"]), (True, True, []))
        self.assertEqual(self.snapshot(), before)

    def load_tool(self):
        spec = importlib.util.spec_from_file_location("timeline_under_test", TOOL)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses look their module up here
        spec.loader.exec_module(module)
        return module

    def test_a_file_changed_after_it_was_read_is_refused(self) -> None:
        module = self.load_tool()
        plan = module.Plan(self.brain.resolve(), self.page.resolve(), module.date(2026, 11, 2))
        self.assertIsNotNone(module.roll_page(plan, "globex / rollout"))
        self.page.write_text(ROLLOUT + "\n- 2026-10-30 — Added by someone else (Opus 5.5)\n", encoding="utf-8")
        with self.assertRaises(module.ActionError) as raised:
            module.commit(plan, dry_run=False)
        self.assertEqual(raised.exception.kind, "conflict")
        self.assertFalse((self.mission / "journal/2026-10.md").exists())
        self.assertIn("Added by someone else", self.read(self.page))

    def test_shift_links_unit(self) -> None:
        module = self.load_tool()
        self.assertEqual(module.shift_links("[a](x.md) and [b](https://e.com) and [c](#h)"), "[a](../x.md) and [b](https://e.com) and [c](#h)")
        self.assertEqual(module.shift_links("no link here"), "no link here")


if __name__ == "__main__":
    unittest.main()
