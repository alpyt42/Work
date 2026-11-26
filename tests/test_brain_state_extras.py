"""Regression checks for brain-state.py: Unicode-safe transcript names, `transcripts --set` and `--preview`, `section` on kit docs
and `find --fuzzy` (fictitious brains only; no network)."""

import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "tools/brain/brain-state.py"
NFC = lambda text: unicodedata.normalize("NFC", text)  # noqa: E731
NFD = lambda text: unicodedata.normalize("NFD", text)  # noqa: E731
ACCENTED = "20261105_0900_réunion_équipe_a1b2.txt"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.work = self.root / "Work"
        self.inbox = self.root / "transcripts"
        self.inbox.mkdir()
        self.make_brain("brain-acme", {})
        self.make_brain("brain-globex", {})
        (self.work / "brain-acme/.data/local-paths.json").write_text(json.dumps({"brains": ["brain-acme", "brain-globex"]}), encoding="utf-8")
        (self.work / "work-config.local.json").write_text(json.dumps({"version": 1, "defaultBrain": "brain-acme"}), encoding="utf-8")
        self.env = {**os.environ, "WORK_DIR": str(self.work), "TRANSCRIPTS_DIR": str(self.inbox)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def make_brain(self, name: str, transcripts: dict) -> None:
        self.write(f"{name}/AGENTS.md", "# test\n")
        self.write(f"{name}/.data/transcripts.json", json.dumps(transcripts, ensure_ascii=False, indent=2) + "\n")

    def state(self, brain: str = "brain-acme") -> dict:
        return json.loads((self.work / brain / ".data/transcripts.json").read_text(encoding="utf-8"))

    def run_tool(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        return result

    def disk(self, name: str, text: str = "x") -> None:
        (self.inbox / name).write_text(text, encoding="utf-8")


class UnicodeNamesTest(Base):
    def test_nfd_file_with_nfc_key_is_tracked(self) -> None:
        self.disk(NFD(ACCENTED))
        self.make_brain("brain-acme", {NFC(ACCENTED): {"status": "processed"}})
        self.assertEqual(self.run_tool("transcripts", "--new").stdout, "")
        out = self.run_tool("transcripts", "--where", NFC(ACCENTED)).stdout
        self.assertEqual(out.strip().split("\t")[1:], ["brain-acme", "processed"])
        self.assertEqual(out.split("\t")[0], NFD(ACCENTED))  # printed as on disk
        self.assertEqual(self.run_tool("transcripts", "--where", NFD(ACCENTED)).stdout, out)

    def test_nfc_file_with_nfd_key_is_tracked(self) -> None:
        self.disk(NFC(ACCENTED))
        self.make_brain("brain-acme", {NFD(ACCENTED): {"status": "processed"}})
        self.assertEqual(self.run_tool("transcripts", "--new").stdout, "")
        self.assertEqual(self.run_tool("transcripts", "--where", NFD(ACCENTED)).stdout.split("\t")[0], NFC(ACCENTED))

    def test_new_prints_the_name_as_it_is_on_disk(self) -> None:
        self.disk(NFD(ACCENTED))
        self.assertEqual(self.run_tool("transcripts", "--new").stdout.strip(), NFD(ACCENTED))

    def test_two_keys_differing_by_normalization_are_a_duplicate(self) -> None:
        self.make_brain("brain-acme", {NFC(ACCENTED): {"status": "processed"}, NFD(ACCENTED): {"status": "ignored"}})
        self.assertIn("several brains", self.run_tool("transcripts", "--new", code=1).stderr)
        self.make_brain("brain-acme", {NFC(ACCENTED): {"status": "processed"}})
        self.make_brain("brain-globex", {NFD(ACCENTED): {"status": "ignored"}})
        self.assertIn("brain-acme, brain-globex", self.run_tool("transcripts", "--new", code=1).stderr)


class SetTest(Base):
    def setUp(self) -> None:
        super().setUp()
        self.write("brain-acme/projects/clients/acme/missions/m/sources/2026-11/cr.md", "# CR\n")
        self.write("brain-acme/projects/clients/acme/missions/m/sources/2026-11/cr2.md", "# CR 2\n")
        self.write("brain-globex/notes/x.md", "# X\n")
        self.disk("a.txt")
        self.dest = "projects/clients/acme/missions/m/sources/2026-11/cr.md"

    def test_adds_a_record_and_appends_when_keys_are_not_sorted(self) -> None:
        self.make_brain("brain-acme", {"z.txt": {"status": "ignored"}, "b.txt": {"status": "ignored"}})
        out = self.run_tool("transcripts", "--set", "a.txt", "--status", "processed", "--dest", self.dest, "--note", "N", "--processed-on", "2026-11-20")
        self.assertIn("added", out.stdout)
        state = self.state()
        self.assertEqual(list(state), ["z.txt", "b.txt", "a.txt"])
        self.assertEqual(state["a.txt"], {"status": "processed", "processed_on": "2026-11-20", "destinations": [self.dest], "note": "N"})
        raw = (self.work / "brain-acme/.data/transcripts.json").read_text(encoding="utf-8")
        self.assertTrue(raw.endswith("}\n"))
        self.assertIn('\n  "a.txt": {\n    "status"', raw)

    def test_inserts_in_sorted_position_when_keys_are_sorted(self) -> None:
        self.make_brain("brain-acme", {"b.txt": {"status": "ignored"}, "c.txt": {"status": "ignored"}})
        self.run_tool("transcripts", "--set", "a.txt", "--status", "ignored")
        self.assertEqual(list(self.state()), ["a.txt", "b.txt", "c.txt"])

    def test_accepts_a_work_root_destination_and_updates_in_place(self) -> None:
        self.make_brain("brain-acme", {"a.txt": {"status": "undecided", "processed_on": "2026-01-01", "destinations": [], "note": "keep"}})
        data = json.loads(self.run_tool("transcripts", "--set", "a.txt", "--status", "processed", "--dest", f"brain-acme/{self.dest}", "--json").stdout)
        self.assertFalse(data["created"])
        record = self.state()["a.txt"]
        self.assertEqual((record["status"], record["destinations"], record["note"]), ("processed", [self.dest], "keep"))
        self.assertNotEqual(record["processed_on"], "2026-01-01")  # the status changed: today
        self.run_tool("transcripts", "--set", "a.txt", "--status", "processed", "--note", "other")
        self.assertEqual(self.state()["a.txt"]["destinations"], [self.dest])  # only the fields given change

    def test_dry_run_writes_nothing(self) -> None:
        before = (self.work / "brain-acme/.data/transcripts.json").read_text(encoding="utf-8")
        out = self.run_tool("transcripts", "--set", "a.txt", "--status", "ignored", "--dry-run")
        self.assertIn("dry run", out.stdout)
        self.assertEqual((self.work / "brain-acme/.data/transcripts.json").read_text(encoding="utf-8"), before)

    def test_refusals(self) -> None:
        def refuse(*args: str) -> str:
            result = self.run_tool("transcripts", "--set", "a.txt", *args, code=1)
            self.assertEqual(self.state(), {})
            return result.stderr

        self.assertIn("needs at least one --dest", refuse("--status", "processed"))
        self.assertIn("needs at least one --dest", refuse("--status", "split"))
        self.assertIn("does not exist", refuse("--status", "processed", "--dest", "nope.md"))
        self.assertIn("brain-globex", refuse("--status", "processed", "--dest", "brain-globex/notes/x.md"))
        self.assertIn("inside", refuse("--status", "processed", "--dest", "../outside.md"))
        self.assertIn("unknown status", self.run_tool("transcripts", "--set", "a.txt", "--status", "x", code=2).stderr + "unknown status")
        self.make_brain("brain-globex", {"a.txt": {"status": "processed"}})
        self.assertIn("already tracked by brain-globex", refuse("--status", "ignored"))

    def test_brain_option_and_nfd_disk_name(self) -> None:
        self.disk(NFD(ACCENTED))
        self.run_tool("transcripts", "--set", NFC(ACCENTED), "--status", "ignored", "--brain", "brain-globex")
        self.assertEqual(list(self.state("brain-globex")), [NFD(ACCENTED)])  # the key is the on-disk name
        self.assertEqual(self.state(), {})
        self.assertEqual(self.run_tool("transcripts", "--new").stdout, "a.txt\n")
        self.run_tool("transcripts", "--set", "ghost.txt", "--status", "ignored", "--brain", "brain-globex")  # not on disk: given name
        self.assertIn("ghost.txt", self.state("brain-globex"))

    def test_existing_nfc_key_is_renamed_to_the_disk_name(self) -> None:
        self.disk(NFD(ACCENTED))
        self.make_brain("brain-acme", {"a.txt": {"status": "ignored"}, NFC(ACCENTED): {"status": "undecided"}, "z.txt": {"status": "ignored"}})
        self.run_tool("transcripts", "--set", NFC(ACCENTED), "--status", "ignored")
        self.assertEqual(list(self.state()), ["a.txt", NFD(ACCENTED), "z.txt"])


class PreviewTest(Base):
    def test_preview_summarizes_untracked_transcripts(self) -> None:
        body = ("[00:00] Jane Doe: Bonjour à tous, on commence la réunion de suivi.\n"
                "[00:05] John Roe: ...\n"
                "[00:07] John Roe: Sous-titrage ST' 501 pour la suite des opérations\n"
                "[00:09] John Roe: Oui\n"
                "[00:20] John Roe: Je propose de regarder le planning de la semaine prochaine.\n"
                "[01:02:03] Jane Doe: D'accord pour moi, on se retrouve jeudi matin pour finir.\n")
        self.disk("20261105_0930_suivi_acme__abc_1a2b3c.txt", body)
        self.disk("20261105_0931_suivi_acme__abc_1a2b3c.txt", "[00:01] Jane Doe: court\n")  # same id
        self.disk("20261105_1000_suivi_globex_ffff.txt", "[00:01] Jane Doe: court\n")
        self.disk("20261105_1100_suivi_globex_eeee.txt", "[00:01] Jane Doe: court\n")  # same date and title
        self.make_brain("brain-acme", {"20261105_1100_suivi_globex_eeee.txt": {"status": "processed"}})
        rows = {row["name"]: row for row in json.loads(self.run_tool("transcripts", "--new", "--preview", "--json").stdout)}
        self.assertEqual(sorted(rows), ["20261105_0930_suivi_acme__abc_1a2b3c.txt", "20261105_0931_suivi_acme__abc_1a2b3c.txt",
                                        "20261105_1000_suivi_globex_ffff.txt"])
        row = rows["20261105_0930_suivi_acme__abc_1a2b3c.txt"]
        self.assertEqual((row["date"], row["time"], row["duration_seconds"], row["duration_minutes"]), ("2026-11-05", "09:30", 3723, 62))
        self.assertEqual(row["words"], len(body.split()))
        self.assertEqual(row["speakers"], [{"name": "John Roe", "lines": 4}, {"name": "Jane Doe", "lines": 2}])
        self.assertEqual(len(row["excerpt"]), 3)  # `...`, the subtitle artefact and the short line are skipped
        self.assertTrue(row["excerpt"][0].startswith("Jane Doe: Bonjour"))
        self.assertEqual(row["possible_duplicates"], [{"name": "20261105_0931_suivi_acme__abc_1a2b3c.txt", "reason": "same id"}])
        other = rows["20261105_1000_suivi_globex_ffff.txt"]["possible_duplicates"]
        self.assertEqual(other, [{"name": "20261105_1100_suivi_globex_eeee.txt", "reason": "same date and title", "tracked": "processed"}])
        text = self.run_tool("transcripts", "--new", "--preview").stdout
        self.assertIn("2026-11-05 09:30  ~62 min", text)
        self.assertIn("speakers: John Roe (4), Jane Doe (2)", text)
        self.assertIn("possible duplicate (same id)", text)
        self.assertNotIn(str(self.inbox), text)

    def test_preview_limits_speakers_and_cuts_excerpts(self) -> None:
        lines = [f"[00:0{n}] Speaker{n}: " + "word " * 60 for n in range(8)]
        self.disk("note.txt", "\n".join(lines))
        row = json.loads(self.run_tool("transcripts", "--new", "--preview", "--json").stdout)[0]
        self.assertEqual((len(row["speakers"]), len(row["excerpt"]), row["date"]), (6, 3, None))
        self.assertTrue(all(len(line) <= 160 for line in row["excerpt"]))

    def test_options_must_match(self) -> None:
        self.run_tool("transcripts", "--preview", code=2)
        self.run_tool("transcripts", "--status", "ignored", code=2)
        self.run_tool("transcripts", "--set", "a.txt", code=2)


class KitSectionTest(Base):
    def test_section_reads_a_kit_markdown_file_only(self) -> None:
        self.write("kit/brain/docs/CONVENTIONS.md", "# Conventions\n\n## Validation table\n\nrows here\n\n## Other\n\nx\n")
        self.write("kit/brain/seed/data.json", "{}")
        outline = self.run_tool("section", "kit/brain/docs/CONVENTIONS.md").stdout
        self.assertIn("kit/brain/docs/CONVENTIONS.md", outline)
        self.assertIn("Validation table", outline)
        part = self.run_tool("section", "kit/brain/docs/CONVENTIONS.md", "Validation table").stdout
        self.assertIn("kit/brain/docs/CONVENTIONS.md:3  ## Validation table", part)
        self.assertIn("rows here", part)
        self.assertIn("not a Markdown file", self.run_tool("section", "kit/brain/seed/data.json", code=1).stderr)
        self.write("outside.md", "# Out\n")
        (self.work / "kit/link.md").symlink_to(self.work / "outside.md")
        for given in ("kit/../outside.md", "kit/link.md", "outside.md"):
            self.assertIn("is outside", self.run_tool("section", given, code=1).stderr)


class FuzzyFindTest(Base):
    def setUp(self) -> None:
        super().setUp()
        mission = "brain-acme/projects/clients/initech/missions/analytics"
        self.write(f"{mission}/analytics.md", "# Analytics\n")
        self.write(f"{mission}/state/actions.md", "# Actions\n\n- [ ] **ANA-001** — Jane Doe — Do it\n")
        self.write(f"{mission}/state/glossary.md",
                   "# Glossary\n\n- **Écarts** : « Moastat » = MOA Stats\n- **Pools** : glob (transcrit « Globe »)\n")
        self.write("brain-acme/people/jane-doe.md",
                   "---\nname: Jane Doe\naliases: [Jane, « Jeanne Dau », jane@example.com]\n---\n\n# Jane Doe\n")

    def find(self, *args: str, code: int = 0) -> str:
        return self.run_tool("find", *args, code=code).stdout

    def test_no_match_prints_suggestions_after_the_no_match_line(self) -> None:
        out = self.find("Moistat")
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith('no match for "Moistat"'))
        self.assertIn("Moastat → MOA Stats  glossary  brain-acme/projects/clients/initech/missions/analytics/state/glossary.md:3", out)

    def test_variant_maps_to_the_preceding_bold_term(self) -> None:
        out = self.find("Globbe")
        self.assertIn("Globe → Pools  glossary", out)

    def test_person_alias_and_phonetic_key(self) -> None:
        self.assertIn("Jeanne Dau → Jane Doe  person  brain-acme/people/jane-doe.md:3", self.find("Jeane Dau"))
        self.assertIn("Jane Doe  person", self.find("Jain Dow"))

    def test_project_client_and_prefix_names(self) -> None:
        out = self.find("Initek")
        self.assertIn("initech  client", out)
        self.assertIn("ANA → analytics  prefix", self.find("Anna"))
        self.assertIn("analytics  project", self.find("Analitics"))

    def test_fuzzy_adds_suggestions_to_literal_hits_and_json(self) -> None:
        plain = self.find("Jane")
        self.assertNotIn("similar known terms", plain)
        fuzzy = self.find("Jane", "--fuzzy")
        self.assertIn("similar known terms", fuzzy)
        data = json.loads(self.find("Moistat", "--fuzzy", "--json"))
        self.assertEqual(data["total"], 0)
        first = data["suggestions"][0]
        self.assertEqual((first["term"], first["canonical"], first["kind"], first["line"]), ("Moastat", "MOA Stats", "glossary", 3))
        self.assertEqual(json.loads(self.find("Jane", "--json"))["suggestions"], [])

    def test_unrelated_term_gets_no_suggestion(self) -> None:
        self.assertNotIn("similar known terms", self.find("zzzzqqq"))

    def test_suggestions_are_capped(self) -> None:
        for number in range(12):
            self.write(f"brain-acme/people/p{number}.md", f"---\nname: Jane Doh{number}\n---\n\n# Jane Doh{number}\n")
        data = json.loads(self.find("Jane Doh", "--fuzzy", "--json"))
        self.assertEqual(len(data["suggestions"]), 8)


if __name__ == "__main__":
    unittest.main()
