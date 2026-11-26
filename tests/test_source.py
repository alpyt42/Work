"""Regression checks for the source tool: minutes rules and the monthly index (no network, temporary brain)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/brain/source.py"

spec = importlib.util.spec_from_file_location("source_tool", TOOL)
source = importlib.util.module_from_spec(spec)
sys.modules["source_tool"] = source
spec.loader.exec_module(source)

SUMMARY = (
    "The team agreed on the rollout plan for the first phase and confirmed the pilot with Jane Doe. "
    "The main blocker is the missing access for the staging environment, which Acme must grant. "
    "Next step is a short follow-up call on Friday."
)

FRONT = """---
date: 2026-11-25
time: "14:00"
type: cr
client: acme
mission: rollout
title: Weekly sync
participants: ["Jane Doe", "John Roe"]
provenance: "Teams recording, 25/11/2026 at 14:00, about {duration}"
reliability: good
written_by: "cr-reunion (Opus 5.5)"
---
"""


def minutes(duration: str = "23 min", body: str | None = None, front: str | None = None) -> str:
    if body is None:
        body = f"""# 2026-11-25 — Weekly sync

Mission page: [rollout](../../rollout.md).

## Summary

{SUMMARY}

## Key points

- **Access:** Acme must grant staging access before the pilot starts; Jane Doe owns the request.
- **Pilot:** the pilot covers two teams for three weeks.

## Decisions

- **Taken** — start the pilot on the first of December — Jane Doe.
- **To confirm** — extend to a third team.

## Actions and follow-up

- **New** — John Roe — send the access request — Friday.
- **New · ACM-12** — Jane Doe — book the room — 03/12.
- **New · not tracked** — everyone — read the plan.
- **Follow-up · ACM-7** — due date moved to 10/12.
"""
    return (front or FRONT).format(duration=duration) + body


class SourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.brain = self.work / "brain-acme"
        self.folder = self.brain / "projects/clients/acme/missions/rollout/sources/2026-11"
        self.folder.mkdir(parents=True)
        (self.brain / "projects/clients/acme/missions/rollout/rollout.md").write_text("# Rollout\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def index(self, *lines: str) -> Path:
        path = self.folder / "index.md"
        path.write_text("# Sources — 2026-11 — rollout\n\n[Back to the mission](../../rollout.md)\n\n" + "".join(l + "\n" for l in lines), encoding="utf-8")
        return path

    def run_tool(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(TOOL), *args, "--brain", str(self.brain)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def check(self, path: Path, code: int | None = None) -> dict:
        data = json.loads(self.run_tool("check", str(path), "--json", code=code if code is not None else (1 if self.has_error(path) else 0)).stdout)
        return data["files"][0]

    def has_error(self, path: Path) -> bool:
        return source.check_text(path.read_text(encoding="utf-8"), str(path), path.parent, path.name).errors > 0

    @staticmethod
    def messages(report: dict, severity: str) -> list[str]:
        return [f["message"] for f in report["findings"] if f["severity"] == severity]

    def ok_index(self, name: str = "2026-11-25-cr-weekly-sync.md", subject: str = "pilot plan and staging access") -> None:
        self.index(f"- 2026-11-25 · cr · [2026-11-25 — Weekly sync]({name}) — {subject}")

    # --- duration and cap ---

    def test_parse_duration_formats(self) -> None:
        cases = {
            "environ 23 min": 23, "23 minutes": 23, "about 45 min": 45, "~1 h 10": 70, "1h10": 70,
            "5,5 min": 5.5, "90 min": 90, "duration 2 hours": 120, "environ 1 heure 15": 75, "1 h": 60,
            "Teams, appel à 18h20, environ 5 min": 5, "call at 14h30, 1h10": 70, "environ 2h": 120,
            "5.5 min": 5.5, "45 mn": 45,
            "de 9h43 à environ 10h05, environ 22 min": 22, "enregistrement de 45 min": 45,
            "réunion de 20 min": 20, "a 20 min call": 20, "durée de 1 h 10": 70,
            "Transcription de l'enregistreur de réunion (Teams), appel du 26/11/2026 à 10h38, environ 23 min": 23,
            "appel à environ 11h30, 1h10": 70, "vers 10h, 25 min": 25,
        }
        for text, minutes_ in cases.items():
            self.assertEqual(source.parse_duration(text), minutes_, text)
        for text in (
            "no duration here", "appel à 18h20", "recorded 25/11/2026", "14h00-14h20", "de 9h43 à 10h05",
            "from 9h30 to 10h15", "appel à environ 11h30", "vers 10h",
        ):
            self.assertIsNone(source.parse_duration(text), text)

    def test_word_cap(self) -> None:
        self.assertEqual(source.word_cap(None), 2000)
        self.assertEqual(source.word_cap(3), 250)
        self.assertEqual(source.word_cap(5), 250)
        self.assertEqual(source.word_cap(5.5), 275)
        self.assertEqual(source.word_cap(23), 1150)
        self.assertEqual(source.word_cap(30), 1500)
        self.assertEqual(source.word_cap(45), 1800)
        self.assertEqual(source.word_cap(60), 2000)
        self.assertEqual(source.word_cap(300), 2000)

    def test_count_words_rules(self) -> None:
        text = "# Title here\n\n- **Bold** item with [link text](https://example.com/very/long/path) <!-- hidden words --> end\n> quote — dash\n"
        self.assertEqual(source.count_words(text), 10)
        self.assertEqual(source.count_words("a — b ## ** - > 12"), 3)

    def test_clean_file_has_no_finding(self) -> None:
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes())
        self.ok_index()
        report = self.check(path, 0)
        self.assertEqual(report["findings"], [])
        self.assertEqual((report["cap"], report["duration_minutes"]), (1150, 23))
        text = self.run_tool("check", str(path)).stdout
        self.assertIn("cap 1150 (duration 23 min)", text)
        self.assertNotIn("error", text.replace("0 errors", ""))

    def test_over_the_cap_is_an_error(self) -> None:
        filler = "\n## Details\n\n" + " ".join(["word"] * 300) + "\n"
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes("5 min", minutes("5 min").split("---\n", 2)[2] + filler))
        self.ok_index()
        report = self.check(path, 1)
        self.assertTrue(any("over the cap of 250" in m for m in self.messages(report, "error")))
        self.assertGreater(report["words"], 250)

    def test_unknown_duration_warns_and_checks_the_2000_cap(self) -> None:
        text = minutes().replace("about 23 min", "no length noted")
        path = self.write("2026-11-25-cr-weekly-sync.md", text)
        self.ok_index()
        report = self.check(path, 0)
        self.assertEqual(report["cap"], 2000)
        self.assertTrue(any("no duration" in m for m in self.messages(report, "warning")))
        big = text + "\n## Details\n\n" + " ".join(["word"] * 2100) + "\n"
        report = self.check(self.write("2026-11-25-cr-weekly-sync.md", big), 1)
        self.assertTrue(any("over the cap of 2000" in m for m in self.messages(report, "error")))

    # --- front matter ---

    def test_front_matter_requirements(self) -> None:
        text = minutes().replace("client: acme\nmission: rollout\n", "").replace("title: Weekly sync\n", "")
        path = self.write("2026-11-25-cr-weekly-sync.md", text)
        self.ok_index()
        errors = self.messages(self.check(path, 1), "error")
        self.assertTrue(any("`title` is missing" in m for m in errors))
        self.assertTrue(any("`client` and `mission`, or `project`" in m for m in errors))
        internal = minutes().replace("client: acme\nmission: rollout\n", "project: setup\n")
        self.assertEqual(self.check(self.write("2026-11-25-cr-weekly-sync.md", internal), 0)["findings"], [])

    def test_front_matter_values_and_placeholders(self) -> None:
        text = minutes().replace("reliability: good", "reliability: great").replace('time: "14:00"', 'time: "25h00"').replace("title: Weekly sync", "title: <title>")
        errors = self.messages(self.check(self.write("2026-11-25-cr-weekly-sync.md", text), 1), "error")
        self.assertTrue(any("reliability" in m for m in errors))
        self.assertTrue(any("`time`" in m for m in errors))
        self.assertTrue(any("`title` still holds the template placeholder" in m for m in errors))

    def test_no_front_matter_and_other_types(self) -> None:
        report = self.check(self.write("2026-11-25-cr-weekly-sync.md", "# Notes\n\n## Summary\n\ntext\n"), 1)
        self.assertIn("no front matter", self.messages(report, "error"))
        mail = self.write("2026-11-25-mail-thing.md", minutes().replace("type: cr", "type: mail"))
        report = self.check(mail, 1)
        self.assertEqual(len(report["findings"]), 1)
        self.assertIn("not minutes", report["findings"][0]["message"])

    def test_file_name_mismatch_is_a_warning(self) -> None:
        path = self.write("2026-11-24-cr-weekly-sync.md", minutes())
        self.index("- 2026-11-24 · cr · [Weekly sync](2026-11-24-cr-weekly-sync.md) — subject")
        report = self.check(path, 0)
        self.assertTrue(any("file name" in m for m in self.messages(report, "warning")))

    # --- sections, summary, key points ---

    def test_sections_required_unknown_empty_and_order(self) -> None:
        body = "# T\n\n## Key points\n\n- one point\n\n## Summary\n\n" + SUMMARY + "\n\n## Decisions\n\n## Mystery\n\ntext\n"
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes(body=body))
        self.ok_index()
        report = self.check(path, 1)
        errors, warnings = self.messages(report, "error"), self.messages(report, "warning")
        self.assertTrue(any("not in the template's order" in m for m in errors))
        self.assertTrue(any("`## Decisions` is empty" in m for m in errors))
        self.assertTrue(any("unknown section `## Mystery`" in m for m in warnings))
        missing = self.write("2026-11-25-cr-weekly-sync.md", minutes(body="# T\n\n## Summary\n\n" + SUMMARY + "\n"))
        self.assertTrue(any("`## Key points` is missing" in m for m in self.messages(self.check(missing, 1), "error")))

    def test_summary_length_warning(self) -> None:
        short = minutes(body="# T\n\n## Summary\n\nToo short.\n\n## Key points\n\n- a point\n")
        report = self.check(self.write("2026-11-25-cr-weekly-sync.md", short))
        self.assertTrue(any("summary holds 2 words" in m for m in self.messages(report, "warning")))
        long_ = minutes(body="# T\n\n## Summary\n\n" + " ".join(["word"] * 71) + "\n\n## Key points\n\n- a point\n")
        self.assertTrue(any("summary holds 71" in m for m in self.messages(self.check(self.write("2026-11-25-cr-weekly-sync.md", long_)), "warning")))
        edge = minutes(body="# T\n\n## Summary\n\n" + " ".join(["word"] * 35) + "\n\n## Key points\n\n- a point\n")
        self.assertFalse(any("summary" in m for m in self.messages(self.check(self.write("2026-11-25-cr-weekly-sync.md", edge)), "warning")))

    def test_key_point_length(self) -> None:
        def body(words: int) -> str:
            return "# T\n\n## Summary\n\n" + SUMMARY + "\n\n## Key points\n\n- " + " ".join(["word"] * words) + " continued\n  on the next line\n"
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes(body=body(60)))
        self.ok_index()
        self.assertEqual(self.check(path, 0)["findings"], [])
        warn = self.check(self.write("2026-11-25-cr-weekly-sync.md", minutes("90 min", body(75))), 0)
        self.assertTrue(any("key point holds" in m and "over 70" in m for m in self.messages(warn, "warning")))
        err = self.check(self.write("2026-11-25-cr-weekly-sync.md", minutes("90 min", body(95))), 1)
        self.assertTrue(any("over 90" in m for m in self.messages(err, "error")))

    # --- tags ---

    def test_decision_and_action_tags(self) -> None:
        bad = minutes().replace("- **Taken** —", "- Taken —").replace("- **New · ACM-12**", "- **New · 12**").replace("- **Follow-up · ACM-7**", "- **Follow-up**")
        report = self.check(self.write("2026-11-25-cr-weekly-sync.md", bad), 1)
        errors = self.messages(report, "error")
        self.assertEqual(len([m for m in errors if "`Decisions` bullet" in m]), 1)
        self.assertEqual(len([m for m in errors if "`Actions and follow-up` bullet" in m]), 2)

    def test_every_valid_tag_is_accepted(self) -> None:
        for tag in ("**Taken**", "**Rejected**", "**To confirm**"):
            self.assertTrue(source.DECISION_TAG.match(tag + " — x"))
        for tag in ("**New**", "**New · ABC-123**", "**New · A1-9**", "**New · not tracked**", "**Follow-up · ABC-123**"):
            self.assertTrue(source.ACTION_TAG.match(tag + " — x"), tag)
        for tag in ("**Done**", "**New · abc-1**", "New", "**Follow-up**"):
            self.assertFalse(source.ACTION_TAG.match(tag), tag)

    # --- leftovers and paths ---

    def test_template_quote_and_local_paths(self) -> None:
        body = minutes().split("---\n", 2)[2].replace(
            "## Summary", "> Template for `<mission>/sources/YYYY-MM/x.md`. Delete this.\n\n## Summary", 1
        ) + "\nSee /Users/someone/file.pdf and ~/docs and C:\\temp and file:///tmp/x.\n"
        report = self.check(self.write("2026-11-25-cr-weekly-sync.md", minutes("90 min", body)), 1)
        errors = self.messages(report, "error")
        self.assertTrue(any("instruction quote" in m for m in errors))
        self.assertEqual(len([m for m in errors if "local path" in m]), 1)
        paths = {s for s in ("/Users/x", "~/x", "C:\\x", "file://x") if source.LOCAL_PATH.search(s)}
        self.assertEqual(len(paths), 4)

    def test_html_comments_are_ignored(self) -> None:
        body = minutes().split("---\n", 2)[2].replace("## Decisions", "<!-- see /Users/x/y\nand more words\n-->\n## Decisions", 1)
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes(body=body))
        self.ok_index()
        self.assertEqual(self.check(path, 0)["findings"], [])

    # --- index check ---

    def test_not_indexed_missing_index_and_long_subject(self) -> None:
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes())
        self.assertTrue(any("no index.md" in m for m in self.messages(self.check(path, 1), "error")))
        self.index("- 2026-11-25 · cr · [Other](2026-11-25-cr-other.md) — subject")
        self.assertTrue(any("not linked from" in m for m in self.messages(self.check(path, 1), "error")))
        self.ok_index(subject=" ".join(["word"] * 16))
        self.assertTrue(any("index subject holds 16 words" in m for m in self.messages(self.check(path, 1), "error")))
        self.ok_index(subject=" ".join(["word"] * 15))
        self.assertEqual(self.check(path, 0)["findings"], [])

    def test_text_output_format_and_exit_code(self) -> None:
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes())
        result = self.run_tool("check", str(path), code=1)
        lines = result.stdout.splitlines()
        self.assertRegex(lines[0], r"2026-11-25-cr-weekly-sync\.md:\d+  error  ")
        self.assertIn("info  body", lines[-1])
        self.run_tool("check", str(self.folder / "missing.md"), code=3)

    def test_several_files_one_exit_code(self) -> None:
        good = self.write("2026-11-25-cr-weekly-sync.md", minutes())
        self.ok_index()
        bad = self.write("2026-11-25-cr-second.md", minutes(body="# T\n\n## Summary\n\n" + SUMMARY + "\n"))
        data = json.loads(self.run_tool("check", str(good), str(bad), "--json", code=1).stdout)
        self.assertEqual([f["errors"] > 0 for f in data["files"]], [False, True])

    # --- index add ---

    def add(self, name: str, subject: str = "short subject", *extra: str, code: int = 0) -> dict:
        args = ["index", "add", str(self.folder / name), *extra]
        if subject is not None:
            args += ["--subject", subject]
        result = self.run_tool(*args, code=code)
        return json.loads(result.stdout)

    def source_file(self, name: str, title: str, date: str = "2026-11-25", time: str = "14:00", kind: str = "cr") -> None:
        front = f'---\ndate: {date}\ntime: "{time}"\ntype: {kind}\nclient: acme\nmission: rollout\ntitle: {title}\n---\n\n# {title}\n'
        if not time:
            front = front.replace('time: ""\n', "")
        self.write(name, front)

    def index_lines(self) -> list[str]:
        return [l for l in (self.folder / "index.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")]

    def test_add_creates_the_index_from_the_template(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        result = self.add("2026-11-25-cr-weekly-sync.md", "pilot plan agreed")
        self.assertTrue(result["created"])
        text = (self.folder / "index.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Sources — 2026-11 — rollout\n"))
        self.assertIn("[Back to the mission](../../rollout.md)", text)
        self.assertNotIn("Template", text)
        self.assertNotIn("<", text)
        self.assertEqual(self.index_lines(), ["- 2026-11-25 · CR · [Weekly sync](2026-11-25-cr-weekly-sync.md) — pilot plan agreed"])
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))

    def test_add_follows_the_style_without_date_prefix_and_upper_case(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.index("- 2026-11-20 · CR · [Kickoff](2026-11-20-cr-kickoff.md) — kickoff held", "- 2026-11-22 · mail · [Thread](2026-11-22-mail-thread.md) — thread")
        self.add("2026-11-25-cr-weekly-sync.md")
        self.assertEqual(self.index_lines()[-1], "- 2026-11-25 · CR · [Weekly sync](2026-11-25-cr-weekly-sync.md) — short subject")

    def test_add_follows_the_style_lower_case_and_date_prefix(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.source_file("2026-11-26-teams-chat.md", "Chat", date="2026-11-26", kind="teams")
        self.index(
            "- 2026-11-20 · cr · [2026-11-20 — Kickoff](2026-11-20-cr-kickoff.md) — kickoff held",
            "- 2026-11-22 · teams · [2026-11-22 — Thread](2026-11-22-teams-thread.md) — thread",
        )
        self.add("2026-11-25-cr-weekly-sync.md")
        self.assertEqual(self.index_lines()[-1], "- 2026-11-25 · cr · [2026-11-25 — Weekly sync](2026-11-25-cr-weekly-sync.md) — short subject")
        self.add("2026-11-26-teams-chat.md")
        self.assertEqual(self.index_lines()[-1], "- 2026-11-26 · teams · [2026-11-26 — Chat](2026-11-26-teams-chat.md) — short subject")

    def test_add_same_type_style_wins_over_the_majority(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.index(
            "- 2026-11-20 · teams · [A](2026-11-20-teams-a.md) — a", "- 2026-11-21 · mail · [B](2026-11-21-mail-b.md) — b",
            "- 2026-11-22 · CR · [C](2026-11-22-cr-c.md) — c",
        )
        self.add("2026-11-25-cr-weekly-sync.md")
        self.assertIn("· CR ·", self.index_lines()[-1])

    def test_add_orders_by_date(self) -> None:
        self.source_file("2026-11-21-cr-mid.md", "Mid", date="2026-11-21")
        self.source_file("2026-11-10-cr-early.md", "Early", date="2026-11-10")
        self.source_file("2026-11-30-cr-late.md", "Late", date="2026-11-30")
        self.index("- 2026-11-05 · CR · [A](2026-11-05-cr-a.md) — a", "- 2026-11-25 · CR · [B](2026-11-25-cr-b.md) — b")
        self.add("2026-11-21-cr-mid.md")
        self.add("2026-11-10-cr-early.md")
        self.add("2026-11-30-cr-late.md")
        self.assertEqual([l[2:12] for l in self.index_lines()], ["2026-11-05", "2026-11-10", "2026-11-21", "2026-11-25", "2026-11-30"])

    def test_add_orders_the_same_date_by_time(self) -> None:
        self.source_file("2026-11-25-cr-morning.md", "Morning", time="09:00")
        self.source_file("2026-11-25-cr-noon.md", "Noon", time="12:00")
        self.source_file("2026-11-25-cr-evening.md", "Evening", time="18:00")
        self.source_file("2026-11-25-cr-afternoon.md", "Afternoon", time="15:00")
        self.index("- 2026-11-25 · CR · [Morning](2026-11-25-cr-morning.md) — m", "- 2026-11-25 · CR · [Evening](2026-11-25-cr-evening.md) — e", "- 2026-11-26 · CR · [Next](2026-11-26-cr-next.md) — n")
        self.add("2026-11-25-cr-afternoon.md")
        self.assertEqual([l.split("](")[1].split(")")[0] for l in self.index_lines()], [
            "2026-11-25-cr-morning.md", "2026-11-25-cr-afternoon.md", "2026-11-25-cr-evening.md", "2026-11-26-cr-next.md"])
        self.add("2026-11-25-cr-noon.md")
        self.assertIn("noon", self.index_lines()[1])

    def test_add_same_date_without_time_goes_after(self) -> None:
        self.source_file("2026-11-25-cr-first.md", "First", time="18:00")
        self.source_file("2026-11-25-cr-notime.md", "No time", time="")
        self.index("- 2026-11-25 · CR · [Old](2026-11-25-cr-old.md) — old", "- 2026-11-26 · CR · [Next](2026-11-26-cr-next.md) — n")
        self.add("2026-11-25-cr-first.md")
        self.add("2026-11-25-cr-notime.md")
        names = [l.split("](")[1].split(")")[0] for l in self.index_lines()]
        self.assertEqual(names, ["2026-11-25-cr-old.md", "2026-11-25-cr-first.md", "2026-11-25-cr-notime.md", "2026-11-26-cr-next.md"])

    def test_add_refuses_a_listed_file(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.index("- 2026-11-25 · CR · [Weekly sync](2026-11-25-cr-weekly-sync.md) — already there")
        before = (self.folder / "index.md").read_text(encoding="utf-8")
        result = self.add("2026-11-25-cr-weekly-sync.md", code=4)
        self.assertEqual(result["kind"], "conflict")
        self.assertEqual((self.folder / "index.md").read_text(encoding="utf-8"), before)

    def test_add_subject_rules(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.assertEqual(self.add("2026-11-25-cr-weekly-sync.md", " ".join(["w"] * 16), code=2)["kind"], "bad_request")
        self.assertEqual(self.add("2026-11-25-cr-weekly-sync.md", None, code=2)["kind"], "bad_request")
        self.assertFalse((self.folder / "index.md").exists())
        self.add("2026-11-25-cr-weekly-sync.md", " ".join(["w"] * 15))
        self.assertEqual(len(self.index_lines()), 1)

    def test_add_dry_run_writes_nothing(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        self.index("- 2026-11-20 · CR · [A](2026-11-20-cr-a.md) — a", "- 2026-11-28 · CR · [B](2026-11-28-cr-b.md) — b")
        before = (self.folder / "index.md").read_text(encoding="utf-8")
        result = self.add("2026-11-25-cr-weekly-sync.md", "subject", "--dry-run")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["position"], 6)
        self.assertIn("[Weekly sync]", result["line"])
        self.assertEqual((self.folder / "index.md").read_text(encoding="utf-8"), before)
        missing = self.folder / "index.md"
        missing.unlink()
        result = self.add("2026-11-25-cr-weekly-sync.md", "subject", "--dry-run")
        self.assertTrue(result["created"])
        self.assertFalse(missing.exists())

    def test_add_input_errors(self) -> None:
        self.write("2026-11-25-cr-nofront.md", "# Nothing\n")
        self.assertEqual(self.add("2026-11-25-cr-nofront.md", code=2)["kind"], "bad_request")
        self.source_file("2026-12-01-cr-wrong-month.md", "Wrong", date="2026-12-01")
        self.assertIn("folder 2026-11", self.add("2026-12-01-cr-wrong-month.md", code=2)["error"])
        self.run_tool("index", "add", str(self.folder / "absent.md"), "--subject", "x", code=3)
        elsewhere = self.brain / "loose.md"
        elsewhere.write_text('---\ndate: 2026-11-25\ntype: cr\ntitle: Loose\n---\n', encoding="utf-8")
        self.assertIn("sources/YYYY-MM", json.loads(self.run_tool("index", "add", str(elsewhere), "--subject", "x", code=2).stdout)["error"])

    def test_added_line_passes_check(self) -> None:
        path = self.write("2026-11-25-cr-weekly-sync.md", minutes())
        self.add(path.name, "pilot plan and staging access")
        self.assertEqual(self.check(path, 0)["findings"], [])

    def test_brain_option_resolves_relative_paths(self) -> None:
        self.source_file("2026-11-25-cr-weekly-sync.md", "Weekly sync")
        relative = "projects/clients/acme/missions/rollout/sources/2026-11/2026-11-25-cr-weekly-sync.md"
        result = self.run_tool("index", "add", relative, "--subject", "found through the brain")
        self.assertIn("found through the brain", result.stdout)


if __name__ == "__main__":
    unittest.main()
