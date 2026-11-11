"""Regression checks for the cross-brain state tool: brain list, transcript states and map (no network, no real brain)."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOL = Path(__file__).resolve().parents[1] / "tools/brain/brain-state.py"


class BrainStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.work = self.root / "Work"
        self.inbox = self.root / "transcripts"
        self.inbox.mkdir()
        for name in ("a.txt", "b.txt", "c.txt", "summary.md"):
            (self.inbox / name).write_text("x", encoding="utf-8")
        self.make_brain("brain", {"a.txt": {"status": "processed"}})
        self.make_brain("brain-perso", {"b.txt": {"status": "undecided"}})
        (self.work / "brain-notes").mkdir()  # no AGENTS.md: not a brain
        self.env = {**os.environ, "WORK_DIR": str(self.work), "TRANSCRIPTS_DIR": str(self.inbox)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_brain(self, name: str, transcripts: dict) -> None:
        data = self.work / name / ".data"
        data.mkdir(parents=True)
        (self.work / name / "AGENTS.md").write_text("# test\n", encoding="utf-8")
        (data / "transcripts.json").write_text(json.dumps(transcripts), encoding="utf-8")

    def run_tool(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True)

    def test_lists_brains_default_first(self) -> None:
        result = self.run_tool("brains")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["brain", "brain-perso"])

    def declare(self, name: str, scope: str, description: str) -> None:
        (self.work / name / ".data/brain.json").write_text(
            json.dumps({"version": 1, "scope": scope, "description": description}), encoding="utf-8"
        )

    def test_brains_print_scope_and_description(self) -> None:
        self.declare("brain", "employer", "Employer context and its clients; never anything personal.")
        self.declare("brain-perso", "personal", "Personal meetings\n  and career,   never any client.")
        result = self.run_tool("brains")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.split("\t") for line in result.stdout.splitlines()]
        self.assertEqual(rows, [
            ["brain", "1 transcript(s) tracked", "employer", "Employer context and its clients; never anything personal."],
            ["brain-perso", "1 transcript(s) tracked", "personal", "Personal meetings and career, never any client."],
        ])

    def test_brains_without_declaration_have_empty_scope_and_description(self) -> None:
        self.declare("brain", "employer", "Employer.")
        rows = [line.split("\t") for line in self.run_tool("brains").stdout.splitlines()]
        self.assertEqual(rows[1], ["brain-perso", "1 transcript(s) tracked", "", ""])

    def test_unreadable_declaration_is_reported(self) -> None:
        (self.work / "brain/.data/brain.json").write_text("{", encoding="utf-8")
        result = self.run_tool("brains")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("brain/.data/brain.json", result.stderr)

    def test_new_ignores_files_tracked_by_any_brain(self) -> None:
        result = self.run_tool("transcripts", "--new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["c.txt"])

    def test_where_reports_owner(self) -> None:
        result = self.run_tool("transcripts", "--where", "b.txt")
        self.assertEqual(result.stdout.strip(), "b.txt\tbrain-perso\tundecided")
        self.assertEqual(self.run_tool("transcripts", "--where", "c.txt").returncode, 1)

    def test_same_transcript_in_two_brains_is_refused(self) -> None:
        state = self.work / "brain-perso/.data/transcripts.json"
        state.write_text(json.dumps({"a.txt": {"status": "undecided"}}), encoding="utf-8")
        result = self.run_tool("transcripts", "--new")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("several brains", result.stderr)

    def test_missing_expected_brain_stops(self) -> None:
        config = self.work / "brain/.data/local-paths.json"
        config.write_text(json.dumps({"brains": ["brain", "brain-perso", "brain-asso"]}), encoding="utf-8")
        result = self.run_tool("transcripts", "--new")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("brain-asso", result.stderr)

    def test_default_brain_is_the_one_of_the_setting_and_carries_the_shared_config(self) -> None:
        self.make_brain("brain-initech", {})
        (self.work / "work-config.local.json").write_text(json.dumps({"version": 1, "defaultBrain": "brain-initech"}), encoding="utf-8")
        result = self.run_tool("brains")
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["brain-initech", "brain", "brain-perso"])
        # Only the default brain's local-paths.json counts: the one of `brain` is ignored, the expected brain of the other is missing.
        (self.work / "brain/.data/local-paths.json").write_text(json.dumps({"brains": ["brain-ghost"]}), encoding="utf-8")
        self.assertEqual(self.run_tool("brains").returncode, 0)
        (self.work / "brain-initech/.data/local-paths.json").write_text(json.dumps({"brains": ["brain-asso"]}), encoding="utf-8")
        result = self.run_tool("brains")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("brain-asso", result.stderr)

    def test_renamed_default_brain_is_found_without_a_setting(self) -> None:
        (self.work / "brain").rename(self.work / "brain-initech")
        (self.work / "brain-perso").rename(self.work / "brain-other")  # two brains and no `brain/`: no default, by name
        env = {key: value for key, value in self.env.items() if key != "TRANSCRIPTS_DIR"}
        self.env = env
        result = self.run_tool("brains")
        self.assertEqual([line.split("\t")[0] for line in result.stdout.splitlines()], ["brain-initech", "brain-other"])
        result = self.run_tool("transcripts", "--new")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("defaultBrain", result.stderr)
        (self.work / "brain-other").rename(self.work / "gone")  # a single brain: it is the default
        (self.work / "brain-initech/.data/local-paths.json").write_text(json.dumps({"brains": ["brain-initech"]}), encoding="utf-8")
        result = self.run_tool("transcripts", "--new")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("transcripts_dir missing from brain-initech/.data/local-paths.json", result.stderr)

    def test_invalid_setting_stops_with_a_clear_message(self) -> None:
        (self.work / "work-config.local.json").write_text(json.dumps({"version": 1, "defaultBrain": "brain-nope"}), encoding="utf-8")
        result = self.run_tool("brains")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("defaultBrain brain-nope is not a brain", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unreadable_transcript_folder_reports_access_error(self) -> None:
        spec = importlib.util.spec_from_file_location("brain_state", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        brains = [self.work / "brain", self.work / "brain-perso"]
        with patch.dict(os.environ, {"TRANSCRIPTS_DIR": str(self.inbox)}), patch.object(
            Path, "iterdir", side_effect=PermissionError(1, "Operation not permitted", str(self.inbox))
        ):
            with self.assertRaises(SystemExit) as error:
                module.cmd_transcripts(brains, new=True, where=None)
        self.assertIn("Access denied", str(error.exception))
        self.assertIn(str(self.inbox), str(error.exception))


class BrainMapTest(unittest.TestCase):
    """`map`: where everything is, on two fictitious brains (`brain-acme` is the default one)."""

    TODAY = "2026-10-25"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name).resolve() / "Work"
        self.work.mkdir()
        self.write("work-config.local.json", json.dumps({"version": 1, "defaultBrain": "brain-acme"}))
        self.env = {**os.environ, "WORK_DIR": str(self.work), "ACTION_NOW": f"{self.TODAY} 09:00"}
        self.make_acme()
        self.make_abacus()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def make_brain(self, name: str, scope: str) -> None:
        self.write(f"{name}/AGENTS.md", "# test\n")
        self.write(f"{name}/.data/brain.json", json.dumps({"version": 1, "scope": scope, "description": "Fixture."}))

    def project(self, folder: str, header: str = "", actions: tuple = (), page: str | None = "", decisions: str | None = None) -> None:
        """A project folder: its register (`actions` are (prefix, state, due) tuples), its page and its decisions when given."""
        lines = [f"- [{state}] **{prefix}-{number:03d}** — Jane Doe — Task {number}" + (f" 📅 {due}" if due else "")
                 for number, (prefix, state, due) in enumerate(actions, 1)]
        sections = {"Open": " /w", "Done": "x", "Cancelled": "-"}
        body = "".join(
            f"## {title}\n" + "".join(line + "\n" for line, (_, state, _) in zip(lines, actions) if state in states) + "\n"
            for title, states in sections.items()
        )
        self.write(f"{folder}/state/actions.md", f"# Actions — {Path(folder).name}\n\n> Register. {header}\n\n{body}")
        if page is not None:
            name = Path(folder).name
            self.write(f"{folder}/{name}.md", page or f"# {name}\n\n- **Status:** active\n\n## Timeline\n- {self.TODAY} — page created\n")
        if decisions is not None:
            self.write(f"{folder}/state/decisions.md", decisions)

    def make_acme(self) -> None:
        self.make_brain("brain-acme", "employer")
        self.write("brain-acme/people/jane-doe.md", "# Jane Doe\n")
        self.write("brain-acme/people/README.md", "# people/\n")
        self.write("brain-acme/people/archive/john-roe.md", "# John Roe\n")
        self.write(
            "brain-acme/inbox/inbox.md",
            "# 📥 Inbox — Scratchpad\n\n> Raw capture.\n\n- call Jane Doe about the schema\nbuy a monitor\n"
            "- 2026-10-20 — triage: 3 item(s) dispatched, 0 question(s) left\n",
        )
        self.write("brain-acme/projects/clients/globex/globex.md", "# Client: Globex\n")
        mission = "brain-acme/projects/clients/globex/missions/migration"
        self.project(
            mission,
            actions=(
                ("GLB", " ", "2026-10-01"),  # to do, overdue
                ("GLB", " ", self.TODAY),  # to do, due today: not overdue
                ("GLB", "/", "2026-10-24"),  # in progress, overdue
                ("GLB", "w", "2026-11-01"),
                ("GLB", "x", "2026-09-01"),  # done: never overdue
                ("GLB", "x", ""),
                ("GLB", "-", ""),  # cancelled: not counted
            ),
            page=(
                "# Mission: Migration\n\n## Summary\n- 2026-12-31 — not a timeline entry\n\n"
                "## Timeline\nPrevious months: [2026-09](journal/2026-09.md)\n- 2026-10-20 — kickoff\n"
                "- 2026-10-24 — workshop\n- 2026-10-02 — preparation\n\n## Notes\n- 2026-12-31 — not a timeline entry\n"
            ),
            decisions=(
                "# Decisions — migration\n\n## Proposed\n\n### Keep the schema (2026-10-01, status: proposed)\n- **Decision:** keep it.\n\n"
                "### Use the batch API (2026-10-02, status: proposed)\n- **Decision:** use it.\n\n"
                "## Accepted\n\n### Archive the logs (2026-09-01, status: accepted)\n- **Decision:** archive.\n\n## Rejected / superseded\n"
            ),
        )
        self.project("brain-acme/projects/clients/globex/missions/support", header="Reserved prefix: `SUP`.", page=None)
        self.project("brain-acme/projects/clients/globex/missions/archive/legacy", actions=(("GLB", "x", "2026-01-05"),))
        self.project("brain-acme/projects/clients/initech/missions/rollout", actions=(("INI", " ", ""),))  # no client index page
        self.project("brain-acme/projects/internal/setup", actions=(("SET", "/", ""),))
        self.project("brain-acme/projects/internal/archive/old-tool", actions=(("OLD", "x", "2025-12-01"),))

    def make_abacus(self) -> None:
        self.make_brain("brain-abacus", "personal")
        self.write("brain-abacus/inbox/inbox.md", "# 📥 Inbox — Scratchpad\n\n> Raw capture.\n\n")
        self.project("brain-abacus/projects/internal/notes", actions=(("NOT", " ", ""),))

    def run_map(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), "map", *args], env=self.env, capture_output=True, text=True)

    def data(self, *args: str) -> dict:
        result = self.run_map("--json", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def brain(self, name: str, *args: str) -> dict:
        return next(brain for brain in self.data(*args)["brains"] if brain["name"] == name)

    def project_of(self, label: str, *args: str) -> dict:
        brain = self.brain("brain-acme", *args)
        projects = [*brain["internal"], *(project for client in brain["clients"] for project in client["projects"])]
        return next(project for project in projects if project["label"] == label)

    def test_default_brain_comes_first_and_is_flagged(self) -> None:
        brains = self.data()["brains"]
        self.assertEqual([(brain["name"], brain["default"], brain["scope"]) for brain in brains],
                         [("brain-acme", True, "employer"), ("brain-abacus", False, "personal")])
        self.assertEqual(self.data()["today"], self.TODAY)

    def test_counts_actions_by_state_and_overdue(self) -> None:
        project = self.project_of("globex / migration")
        self.assertEqual(project["actions"], {"open": 2, "in_progress": 1, "waiting": 1, "done": 2, "overdue": 2})
        self.assertEqual(self.project_of("initech / rollout")["actions"], {"open": 1, "in_progress": 0, "waiting": 0, "done": 0, "overdue": 0})

    def test_prefix_comes_from_the_ids_then_from_the_register_header(self) -> None:
        self.assertEqual(self.project_of("globex / migration")["prefix"], "GLB")
        self.assertEqual(self.project_of("globex / support")["prefix"], "SUP")  # no action yet: reserved in the header
        self.assertEqual(self.brain("brain-abacus")["internal"][0]["prefix"], "NOT")
        self.write("brain-acme/projects/internal/setup/state/actions.md", "# Actions — setup\n\n## Open\n")
        self.assertIsNone(self.project_of("setup")["prefix"])
        # every action archived: the prefix of the archive, the one `action.py create` would use
        self.write("brain-acme/projects/internal/setup/state/actions-archive-2026.md", "## Done\n- [x] **SET-001** — Jane Doe — Old task ✅ 2026-01-05\n")
        self.assertEqual(self.project_of("setup")["prefix"], "SET")

    def test_page_path_is_relative_to_the_work_root_and_null_when_missing(self) -> None:
        migration = self.project_of("globex / migration")
        self.assertEqual(migration["page"], "brain-acme/projects/clients/globex/missions/migration/migration.md")
        self.assertEqual(migration["register"], "brain-acme/projects/clients/globex/missions/migration/state/actions.md")
        self.assertTrue((self.work / migration["page"]).is_file())
        support = self.project_of("globex / support")
        self.assertIsNone(support["page"])
        self.assertEqual(support["register"], "brain-acme/projects/clients/globex/missions/support/state/actions.md")
        text = self.run_map().stdout
        self.assertIn("brain-acme/projects/clients/globex/missions/support/support.md (missing)", text)

    def test_proposed_decisions_are_counted_when_the_register_exists(self) -> None:
        self.assertEqual(self.project_of("globex / migration")["decisions_proposed"], 2)
        self.assertIsNone(self.project_of("globex / support")["decisions_proposed"])
        self.write("brain-acme/projects/clients/globex/missions/support/state/decisions.md", "# Decisions — support\n\n## Proposed\n\n## Accepted\n")
        self.assertEqual(self.project_of("globex / support")["decisions_proposed"], 0)

    def test_last_timeline_entry_is_the_latest_date_of_the_timeline_section(self) -> None:
        self.assertEqual(self.project_of("globex / migration")["last_timeline"], "2026-10-24")  # not first, not the 2026-12-31 outside it
        self.assertEqual(self.project_of("setup")["last_timeline"], self.TODAY)
        self.assertIsNone(self.project_of("globex / support")["last_timeline"])

    def labels(self, *args: str) -> dict:
        brain = self.brain("brain-acme", *args)
        projects = [*brain["internal"], *(project for client in brain["clients"] for project in client["projects"])]
        return {project["label"]: project["archived"] for project in projects}

    def test_archived_projects_are_hidden_by_default_and_shown_by_archived_or_all(self) -> None:
        self.assertEqual(self.labels(), {"setup": False, "globex / migration": False, "globex / support": False, "initech / rollout": False})
        self.assertEqual(self.labels("--archived"), {"old-tool": True, "globex / legacy": True})
        self.assertEqual(self.labels("--all"), {
            "setup": False, "old-tool": True, "globex / migration": False, "globex / support": False, "globex / legacy": True,
            "initech / rollout": False,
        })
        self.assertNotIn("[archived]", self.run_map().stdout)
        for args in (("--all",), ("--archived",)):
            archived = [line for line in self.run_map(*args).stdout.splitlines() if "[archived]" in line]
            self.assertEqual(sorted(line.split()[0] for line in archived), ["legacy", "old-tool"])

    def test_archived_scope_keeps_only_the_clients_with_archived_missions(self) -> None:
        self.assertEqual([client["name"] for client in self.brain("brain-acme", "--archived")["clients"]], ["globex"])
        self.assertEqual(self.brain("brain-abacus", "--archived")["internal"], [])
        self.assertEqual([client["name"] for client in self.brain("brain-acme", "--all")["clients"]], ["globex", "initech"])
        text = self.run_map("--archived").stdout
        self.assertNotIn("client initech", text)
        self.assertNotIn("migration", text)

    def test_scope_and_left_out_count_the_projects_not_shown(self) -> None:
        for args, scope, acme, abacus in (((), "live", 2, 0), (("--archived",), "archived", 4, 1), (("--all",), "all", 0, 0)):
            data = self.data(*args)
            self.assertEqual(data["scope"], scope)
            self.assertEqual({brain["name"]: brain["left_out"] for brain in data["brains"]}, {"brain-acme": acme, "brain-abacus": abacus})

    def test_text_says_how_many_projects_are_not_shown(self) -> None:
        self.assertIn("  (2 archived projects not shown: map --archived, or map --all for both)", self.run_map().stdout)
        archived = self.run_map("--archived").stdout
        self.assertIn("  (4 live projects not shown: map, or map --all for both)", archived)
        self.assertIn("  (1 live project not shown: map, or map --all for both)", archived)
        self.assertNotIn("not shown", self.run_map("--all").stdout)
        (self.work / "brain-acme/projects/internal/archive/old-tool").rename(self.work / "brain-acme/projects/internal/old-tool")
        self.assertIn("  (1 archived project not shown: map --archived, or map --all for both)", self.run_map().stdout)

    def make_other_places(self) -> None:
        """A whole archived client with a mission, and one project in each earlier place: `clients/<c>/archive/<m>`, `archive/<p>`."""
        self.write("brain-acme/projects/clients/archive/soylent/soylent.md", "# Client: Soylent\n")
        self.project("brain-acme/projects/clients/archive/soylent/missions/pilot", actions=(("SOY", "x", "2026-01-05"),))
        self.project("brain-acme/projects/clients/initech/archive/early", actions=(("INI", "x", "2026-01-05"),))
        self.project("brain-acme/projects/archive/legacy-tool", actions=(("LEG", "x", "2026-01-05"),))

    def test_an_archived_client_and_the_earlier_places_read_like_live_ones_with_the_archived_flag(self) -> None:
        self.make_other_places()
        self.assertEqual(self.labels("--archived"), {"old-tool": True, "legacy-tool": True, "globex / legacy": True, "initech / early": True,
                                                    "soylent / pilot": True})
        self.assertEqual(self.labels(), {"setup": False, "globex / migration": False, "globex / support": False, "initech / rollout": False})
        projects = {project["label"]: project for client in self.brain("brain-acme", "--archived")["clients"] for project in client["projects"]}
        self.assertEqual((projects["soylent / pilot"]["kind"], projects["soylent / pilot"]["client"], projects["soylent / pilot"]["name"]),
                         ("client", "soylent", "pilot"))
        self.assertEqual(projects["soylent / pilot"]["register"],
                         "brain-acme/projects/clients/archive/soylent/missions/pilot/state/actions.md")
        self.assertEqual(projects["initech / early"]["client"], "initech")
        internal = {project["label"]: project for project in self.brain("brain-acme", "--archived")["internal"]}
        self.assertEqual((internal["legacy-tool"]["kind"], internal["legacy-tool"]["client"]), ("internal", None))

    def test_an_archived_client_is_listed_with_the_archived_flag_by_archived_and_all_only(self) -> None:
        self.make_other_places()
        line = "  client soylent [archived]  brain-acme/projects/clients/archive/soylent/soylent.md"
        for args in (("--archived",), ("--all",)):
            self.assertIn(line, self.run_map(*args).stdout.splitlines())
            clients = {client["name"]: client for client in self.brain("brain-acme", *args)["clients"]}
            self.assertEqual((clients["soylent"]["archived"], clients["soylent"]["page"]),
                             (True, "brain-acme/projects/clients/archive/soylent/soylent.md"))
            self.assertIs(clients["globex"]["archived"], False)
            self.assertEqual([project["label"] for project in clients["soylent"]["projects"]], ["soylent / pilot"])
        text = self.run_map().stdout
        self.assertNotIn("soylent", text)
        self.assertNotIn("client archive", text)
        for args in ((), ("--archived",), ("--all",)):
            names = [client["name"] for client in self.brain("brain-acme", *args)["clients"]]
            self.assertNotIn("archive", names)  # `clients/archive` is the shelf, never a client
        self.assertEqual([client["name"] for client in self.brain("brain-acme", "--archived")["clients"]], ["globex", "initech", "soylent"])
        self.assertNotIn("migration", self.run_map("--archived").stdout)

    def test_an_archived_client_without_a_page_and_one_with_the_same_name_as_a_live_client(self) -> None:
        self.make_other_places()
        self.project("brain-acme/projects/clients/archive/initech/missions/oldpilot", actions=(("INI", "x", "2026-01-05"),), page=None)
        both = [(client["name"], client["archived"]) for client in self.brain("brain-acme", "--all")["clients"]]
        self.assertEqual(both, [("globex", False), ("initech", False), ("initech", True), ("soylent", True)])
        text = self.run_map("--all").stdout
        self.assertIn("  client initech [archived]  (no index page)", text)
        self.assertIn("brain-acme/projects/clients/archive/initech/missions/oldpilot/oldpilot.md (missing)", text)

    def test_the_left_out_count_includes_the_archived_clients_and_the_earlier_places(self) -> None:
        self.make_other_places()
        self.assertIn("  (5 archived projects not shown: map --archived, or map --all for both)", self.run_map().stdout)
        self.assertEqual(self.data()["brains"][0]["left_out"], 5)

    def test_archived_and_all_are_mutually_exclusive(self) -> None:
        result = self.run_map("--archived", "--all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed with", result.stderr)

    def test_brain_option_keeps_one_brain_and_refuses_an_unknown_one(self) -> None:
        self.assertEqual([brain["name"] for brain in self.data("--brain", "brain-abacus")["brains"]], ["brain-abacus"])
        result = self.run_map("--brain", "brain-nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown brain brain-nope", result.stderr)
        self.assertIn("brain-acme, brain-abacus", result.stderr)

    def test_json_keys_are_stable(self) -> None:
        data = self.data()
        self.assertEqual(sorted(data), ["brains", "scope", "today"])
        self.assertEqual(data["scope"], "live")
        brain = data["brains"][0]
        self.assertEqual(sorted(brain), ["clients", "default", "inbox_lines", "internal", "left_out", "name", "people", "scope"])
        client = brain["clients"][0]
        self.assertEqual(sorted(client), ["archived", "name", "page", "projects"])
        self.assertIs(client["archived"], False)
        project = client["projects"][0]
        self.assertEqual(sorted(project), ["actions", "archived", "client", "decisions_proposed", "kind", "label", "last_timeline", "name", "page", "prefix", "register"])
        self.assertEqual(sorted(project["actions"]), ["done", "in_progress", "open", "overdue", "waiting"])
        self.assertEqual((project["kind"], project["client"], project["name"]), ("client", "globex", "migration"))
        internal = brain["internal"][0]
        self.assertEqual((internal["kind"], internal["client"], internal["label"]), ("internal", None, "setup"))

    def test_clients_are_listed_with_their_index_page(self) -> None:
        clients = {client["name"]: client["page"] for client in self.brain("brain-acme")["clients"]}
        self.assertEqual(clients, {"globex": "brain-acme/projects/clients/globex/globex.md", "initech": None})
        self.assertIn("client initech  (no index page)", self.run_map().stdout)

    def test_counts_people_pages_and_inbox_lines(self) -> None:
        acme = self.brain("brain-acme")
        self.assertEqual((acme["people"], acme["inbox_lines"]), (1, 2))  # README, archive and the triage log line do not count
        abacus = self.brain("brain-abacus")
        self.assertEqual((abacus["people"], abacus["inbox_lines"]), (0, 0))
        self.write("brain-abacus/inbox/inbox.md", "# Inbox\n\n> Raw capture.\n\n---\n\n> a quote below the separator\n\n- a line\n")
        self.assertEqual(self.brain("brain-abacus")["inbox_lines"], 2)
        (self.work / "brain-abacus/inbox/inbox.md").unlink()
        self.assertEqual(self.brain("brain-abacus")["inbox_lines"], 0)

    def test_text_has_one_aligned_line_per_project_grouped_by_brain_and_client(self) -> None:
        lines = self.run_map().stdout.splitlines()
        self.assertEqual(lines[0], "brain-acme (employer, default) — people 1 — inbox 2 to triage")
        self.assertEqual([line for line in lines if not line.startswith("    ")][:8], [
            lines[0],
            "  client globex  brain-acme/projects/clients/globex/globex.md",
            "  client initech  (no index page)",
            "  internal",
            "  (2 archived projects not shown: map --archived, or map --all for both)",
            "brain-abacus (personal) — people 0 — inbox empty",
            "  internal",
            "",
        ])
        projects = [line for line in lines if line.startswith("    ")]
        self.assertEqual([line.split()[0] for line in projects], ["migration", "support", "rollout", "setup", "notes"])
        acme = projects[:4]
        self.assertEqual(len({line.index("open ") for line in acme}), 1)
        self.assertEqual(len({line.index("brain-acme/") for line in acme}), 1)
        self.assertIn("GLB  open 2  doing 1  wait 1  done 2  late 2  dec 2  last 2026-10-24  brain-acme/projects/clients/globex/missions/migration/migration.md", acme[0])
        self.assertIn("SUP  open 0  doing 0  wait 0  done 0  late 0  dec -  last -", acme[1])

    def test_map_writes_nothing(self) -> None:
        def snapshot() -> list:
            return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.work.rglob("*"))
        before = snapshot()
        self.assertEqual(self.run_map("--all").returncode, 0)
        self.assertEqual(self.run_map("--json").returncode, 0)
        self.assertEqual(snapshot(), before)


class BrainContextTest(unittest.TestCase):
    """`brief`, `due`, `changes`, `find`, `section` and `person`: compact read-only context, on the fictitious brains of BrainMapTest."""

    TODAY = BrainMapTest.TODAY
    MIGRATION = "brain-acme/projects/clients/globex/missions/migration"
    setUp, tearDown, write, make_brain, project = (BrainMapTest.setUp, BrainMapTest.tearDown, BrainMapTest.write,
                                                   BrainMapTest.make_brain, BrainMapTest.project)
    make_acme, make_abacus = BrainMapTest.make_acme, BrainMapTest.make_abacus

    def run_tool(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def lines(self, *args: str) -> list[str]:
        return self.run_tool(*args).stdout.splitlines()

    def data(self, *args: str) -> dict:
        return json.loads(self.run_tool(*args, "--json").stdout)

    ROLLOUT = "brain-acme/projects/clients/initech/missions/rollout"
    KICKOFF = f"{ROLLOUT}/sources/2026-10/2026-10-13-cr-kickoff.md"

    def make_memory(self) -> None:
        """What `find`, `section` and `person` read beyond the registers: people with aliases, minutes, journal, workstream, note, glossary."""
        self.env.pop("BRAIN_OWNER", None)  # the owner of a brain is the one its `.data/doctor.json` names, if any
        self.write("brain-acme/people/jane-doe.md", (
            "---\nname: Jane Doe\norganization: Globex\nmissions: [migration, rollout]\naliases: [\"Jane D.\", JD, 'Jeanne Doe']\n"
            "role: Data lead, sponsor of the migration\nemail: jane.doe@globex.example\nupdated: 2026-10-20\n---\n\n# Jane Doe\n\n"
            "- **Projects:** migration (sponsor), rollout (reviewer)\n\n## Role and scope\nOwns the data platform and signs off the plan.\n\n"
            "## Interaction log\n- 2026-10-13 — asked for the cutover plan\n"
        ))
        self.write("brain-acme/people/jane-roe.md", (
            "---\nname: Jane Roe\norganization: Initech\nmissions: [rollout]\naliases: [JR]\nrole: Rollout manager\nupdated: 2026-10-01\n---\n\n"
            "# Jane Roe\n\n## Role and scope\nRuns the rollout.\n"
        ))
        self.write("brain-acme/people/john-smith.md", (
            "# John Smith\n\n- **Role:** architect\n- **Team / project:** platform team\n\n## Context\nJoined the migration in October.\n\n"
            "## Running log\n- 2026-10-14 — reviewed the schema\n"
        ))
        self.write("brain-acme/people/zoe-lefevre.md", "---\nname: Zoé Lefèvre\naliases:\n  - Zoé L.\n  - Zozo\nrole: Trainer\n---\n\n# Zoé Lefèvre\n")
        self.write(f"{self.ROLLOUT}/state/actions.md", (
            "# Actions — rollout\n\n## Open\n"
            "- [ ] **INI-001** — Jane Roe — Prepare the pilot site 📅 2026-10-20\n"
            "    - source: [Kickoff](../sources/2026-10/2026-10-13-cr-kickoff.md)\n    - created: 2026-10-13 10:00\n"
            "    - 14/10: site chosen with the Zürich team\n    - 15/10: access requested\n"
            "- [/] **INI-002** — Jane — Draft the training plan 📅 2026-11-03\n"
            "- [w] **INI-003** — John — Order the badges\n"
            "- [ ] **INI-004** — Jane Doe / John Smith — Review the cutover checklist 📅 2026-10-30\n"
            "- [ ] **INI-005** — JD — Send the steering deck\n"
            "- [ ] **INI-006** — Zoé, then Jane Roe — Book the room\n"
            "\n## Done\n- [x] **INI-007** — Jane Roe — Sign the charter ✅ 2026-10-10\n\n## Cancelled\n"
        ))
        self.write(f"{self.ROLLOUT}/state/decisions.md", (
            "# Decisions — rollout\n\n## Proposed\n\n### Pilot in one site (2026-10-13, status: proposed)\n"
            "- **Context:** the Zürich site is ready.\n- **Decision:** pilot there first.\n\n## Accepted\n\n## Rejected / superseded\n"
        ))
        self.write(f"{self.ROLLOUT}/state/glossary.md", "# Glossary — rollout\n\n- **Pilot**: the first site, Zürich.\n")
        self.write(f"{self.ROLLOUT}/rollout.md", "# rollout\n\n## Summary\n- Pilot in Zürich, then the other sites.\n\n## Timeline\n- 2026-10-13 — kickoff\n")
        self.write(self.KICKOFF, (
            "---\ndate: 2026-10-13\ntype: cr\ntitle: Kickoff\nparticipants: [\"Jane Roe\", \"John Smith\"]\n---\n\n# 2026-10-13 — Kickoff\n\n"
            "Mission page: [rollout](../../rollout.md).\n\n## Summary\n\nThe pilot starts in Zürich on 3 November. The badge order waits for ticket REQ-0042.\n\n"
            "## Key points\n\n- **Pilot:** one site first.\n- **Training:** Jane drafts the plan.\n\n### Open questions\n\n- Who pays for the badges?\n\n"
            "## Décisions\n\n- **Taken** — pilot in one site — Jane Roe.\n\n## Actions and follow-up\n\n- **New** — John — order the badges.\n"
        ))
        self.write(f"{self.ROLLOUT}/sources/2026-10/index.md", "# Sources — 2026-10 — rollout\n\n- 2026-10-13 · CR · [Kickoff](2026-10-13-cr-kickoff.md) — pilot in Zürich\n")
        self.write(f"{self.ROLLOUT}/sources/2026-09/2026-09-30-mail-badges.md", (
            "---\ndate: 2026-09-30\ntype: mail\n---\n\n# 2026-09-30 — Badges\n\n## Résumé\n\nLes badges seront commandés après le pilote à Zürich.\n\n"
            "## Détail\n\n- Zürich : 40 badges.\n- Zürich : livraison en novembre.\n- Zürich : contact sur place.\n- Zürich : budget validé.\n"
        ))
        self.write(f"{self.ROLLOUT}/journal/2026-09.md", "# Journal — 2026-09 — rollout\n\n- 2026-09-28 — first contact about the Zürich pilot\n")
        self.write(f"{self.ROLLOUT}/journal/2026-08.md", "# Journal — 2026-08 — rollout\n\n- 2026-08-30 — proposal sent, Zürich mentioned\n")
        self.write(f"{self.ROLLOUT}/workstreams/training.md", "# Training\n\n## Plan\nThe Zürich trainers start in November.\n\n## Risks\n- none yet\n")
        self.write(f"{self.ROLLOUT}/notes/2026-10-14-pilot-ideas.md", "# Pilot ideas\n\nZürich first, then Geneva.\n")

    # --- brief ---

    def test_brief_prints_state_actions_decisions_timeline_and_reading_list(self) -> None:
        self.assertEqual(self.lines("brief", "globex/migration"), [
            "brain-acme — globex / migration — today 2026-10-25",
            "",
            f"State (`## Summary`, the first summary section: the page has no `## Current state`) — {self.MIGRATION}/migration.md:3",
            "  - 2026-12-31 — not a timeline entry",
            "",
            "Actions: open 2  doing 1  wait 1  done 2  late 2 — decisions: proposed 2  accepted 1",
            "Late:",
            "  GLB-001 [ ] 2026-10-01  Jane Doe — Task 1",
            "  GLB-003 [/] 2026-10-24  Jane Doe — Task 3",
            "Open, doing `/` first, then to do ` ` and waiting `w`:",
            "  GLB-002 [ ] 2026-10-25  Jane Doe — Task 2",
            "  GLB-004 [w] 2026-11-01  Jane Doe — Task 4",
            "",
            "Decisions, proposed and accepted, most recent first:",
            "  no. 2 [proposed] 2026-10-02  Use the batch API",
            "  no. 1 [proposed] 2026-10-01  Keep the schema",
            "  no. 3 [accepted] 2026-09-01  Archive the logs",
            "",
            "Timeline, latest entries:",
            "  2026-10-24  workshop",
            "  2026-10-20  kickoff",
            "  2026-10-02  preparation",
            "",
            "Load next, only the part the task needs:",
            f"  outline    uv run tools/brain/brain-state.py section {self.MIGRATION}/migration.md",
            "  actions    uv run tools/brain/action.py list --project globex/migration --state open --table",
            "  decisions  uv run tools/brain/decision.py list --project globex/migration --table",
        ])

    def test_brief_points_to_commands_that_load_a_part_not_to_files(self) -> None:
        self.make_memory()
        text = self.lines("brief", "rollout")
        self.assertEqual(text[text.index("Load next, only the part the task needs:") + 1:], [
            f"  outline    uv run tools/brain/brain-state.py section {self.ROLLOUT}/rollout.md",
            "  actions    uv run tools/brain/action.py list --project initech/rollout --state open --table",
            "  decisions  uv run tools/brain/decision.py list --project initech/rollout --table",
            f"  sources    uv run tools/brain/brain-state.py section {self.ROLLOUT}/sources/2026-10/index.md:1",  # the latest month
        ])
        # outside the default brain, action.py and decision.py are told which brain
        self.assertEqual(self.lines("brief", "notes")[-2:], [
            "  outline  uv run tools/brain/brain-state.py section brain-abacus/projects/internal/notes/notes.md",
            "  actions  uv run tools/brain/action.py --brain brain-abacus list --project notes --state open --table",
        ])
        # a short name two projects of the brain share: the project folder from the brain
        self.project("brain-acme/projects/archive/setup", actions=(("OLD", "x", ""),), page=None)
        self.assertIn("  actions  uv run tools/brain/action.py list --project projects/internal/setup --state open --table",
                      self.lines("brief", "brain-acme/projects/internal/setup"))
        # the commands run as printed, from the Work root, and each one prints a part of the project
        for line in self.lines("brief", "rollout")[-4:] + self.lines("brief", "notes")[-2:]:
            script, *args = line.split("uv run ")[1].split()
            result = subprocess.run([sys.executable, str(TOOL.parent / Path(script).name), *args], cwd=self.work, env=self.env,
                                    capture_output=True, text=True, check=False)
            self.assertEqual((result.returncode, bool(result.stdout.strip())), (0, True), line + result.stdout + result.stderr)

    def test_brief_prefers_the_current_state_section_and_caps_its_words(self) -> None:
        page = (
            "# Mission: Migration\n\n## Summary\n- the scope\n\n## Current state\n- one two three four\n\n  - five six seven\n"
            "### Risks\n- eight nine\n\n## Timeline\n- 2026-10-20 — kickoff\n  continued on a second line\n"
        )
        self.write(f"{self.MIGRATION}/migration.md", page)
        text = self.lines("brief", "globex / migration")
        start = text.index(f"State (`## Current state`) — {self.MIGRATION}/migration.md:6")
        self.assertEqual(text[start + 1:start + 5], ["  - one two three four", "    - five six seven", "  ### Risks", "  - eight nine"])
        self.assertNotIn("truncated", "\n".join(text))
        text = self.lines("brief", "globex/migration", "--words", "7")
        self.assertEqual(text[start + 1:start + 4], ["  - one two three four", "    - five …", f"  (truncated, 7 more words: {self.MIGRATION}/migration.md)"])
        state = self.data("brief", "globex/migration", "--words", "7")["state"]
        self.assertEqual((state["heading"], state["fallback"], state["line"], state["truncated_words"]), ("Current state", False, 6, 7))
        self.assertIn("  2026-10-20  kickoff", text)  # first line of the entry only

    def test_brief_says_when_the_page_has_no_state_section_and_skips_missing_files(self) -> None:
        text = self.lines("brief", "initech/rollout")
        self.assertIn("State: the project page has no `## Current state` or summary section", text)
        self.assertNotIn("Decisions, proposed and accepted, most recent first:", text)
        self.assertEqual(text[text.index("Load next, only the part the task needs:") + 1:], [
            "  outline  uv run tools/brain/brain-state.py section brain-acme/projects/clients/initech/missions/rollout/rollout.md",
            "  actions  uv run tools/brain/action.py list --project initech/rollout --state open --table",
        ])
        self.assertIsNone(self.data("brief", "initech/rollout")["state"])

    def test_brief_caps_actions_and_decisions_with_a_more_line(self) -> None:
        text = self.lines("brief", "globex/migration", "--limit", "3", "--decisions", "1")  # below the defaults
        self.assertEqual([line.split()[0] for line in text if line.startswith("  GLB-")], ["GLB-001", "GLB-003", "GLB-002"])
        self.assertEqual(text.count("  +1 more"), 1)
        self.assertEqual(text.count("  +2 more"), 1)
        data = self.data("brief", "globex/migration", "--limit", "1", "--decisions", "1")
        self.assertEqual(([item["id"] for item in data["actions"]["late"]], data["actions"]["open"], data["actions"]["more"]), (["GLB-001"], [], 3))
        self.assertEqual(([item["number"] for item in data["decisions"]["items"]], data["decisions"]["more"]), ([2], 2))

    def test_brief_fills_the_timeline_from_the_journal(self) -> None:
        self.write(f"{self.MIGRATION}/journal/2026-09.md", "# Journal — 2026-09 — Migration\n\n- 2026-09-30 — audit\n- 2026-09-12 — scoping\n- 2026-09-02 — first call\n")
        self.write(f"{self.MIGRATION}/journal/2026-08.md", "# Journal — 2026-08 — Migration\n\n- 2026-08-30 — proposal\n")
        timeline = self.data("brief", "globex/migration")["timeline"]
        self.assertEqual([item["date"] for item in timeline], ["2026-10-24", "2026-10-20", "2026-10-02", "2026-09-30", "2026-09-12"])
        self.assertEqual((timeline[3]["path"], timeline[3]["line"], timeline[3]["text"]), (f"{self.MIGRATION}/journal/2026-09.md", 3, "audit"))

    def test_brief_json_has_the_same_fields(self) -> None:
        data = self.data("brief", "globex/migration")
        self.assertEqual(sorted(data), ["actions", "archived", "brain", "counts", "decisions", "load_next", "project", "repos", "state",
                                        "timeline", "today"])
        self.assertEqual(data["counts"], {"open": 2, "in_progress": 1, "waiting": 1, "done": 2, "overdue": 2,
                                          "decisions_proposed": 2, "decisions_accepted": 1})
        self.assertEqual(data["actions"]["late"][0], {"id": "GLB-001", "state": " ", "due": "2026-10-01", "owner": "Jane Doe", "title": "Task 1", "late": True})
        self.assertEqual(data["decisions"]["items"][0], {"number": 2, "state": "proposed", "date": "2026-10-02", "title": "Use the batch API"})
        self.assertEqual([item["what"] for item in data["load_next"]], ["outline", "actions", "decisions"])
        self.assertEqual(data["load_next"][1], {"what": "actions", "command": "uv run tools/brain/action.py list --project globex/migration --state open --table"})
        self.assertIsNone(data["repos"])  # no repository catalog in the brain

    def catalog(self, brain: str, *entries: tuple) -> None:
        """The brain's repository catalog: (path, project or None) entries, with fictitious SSH URLs."""
        repositories = [{"path": path, "url": f"git@example.com:{path.split('/', 1)[1]}.git", **({"project": project} if project else {})}
                        for path, project in entries]
        self.write(f"{brain}/.data/client-repos.json", json.dumps({"schema_version": 2, "repositories": repositories}))

    def test_brief_counts_the_project_repositories_of_the_catalog_by_name(self) -> None:
        self.catalog("brain-acme",
                     ("repos/globex/api", "globex/migration"),
                     ("repos/globex/web", "clients/globex/missions/migration"),  # any name `brief` accepts
                     ("repos/globex/batch", "globex/migration"),
                     ("repos/globex/desk", "globex/support"),  # another project
                     ("repos/initech/tool", None))  # no project: never counted
        (self.work / "repos/globex/api/.git").mkdir(parents=True)
        (self.work / "repos/globex/batch/.git").mkdir(parents=True)
        (self.work / "repos/globex/web").mkdir(parents=True)  # a folder without .git is not a clone
        text = self.lines("brief", "globex/migration")
        line = "Repos: 3 in the catalog, 2 present here (api, batch), 1 missing — `uv run tools/repos/client-repos.py list --project globex/migration`"
        self.assertEqual(text[text.index("Load next, only the part the task needs:") - 2:text.index("Load next, only the part the task needs:")],
                         [line, ""])
        self.assertNotIn("repos/", "\n".join(text).replace("tools/repos/", ""))  # names only, never a path
        self.assertNotIn("example.com", "\n".join(text))  # never a URL
        self.assertEqual(self.data("brief", "globex/migration")["repos"], {
            "count": 3, "present": ["api", "batch"], "missing": ["web"],
            "command": "uv run tools/repos/client-repos.py list --project globex/migration"})
        self.assertFalse([line for line in self.lines("brief", "initech/rollout") if line.startswith("Repos:")])
        self.assertIsNone(self.data("brief", "initech/rollout")["repos"])
        # outside the default brain, the command names the brain's catalog
        self.catalog("brain-abacus", ("repos/abacus/notes-app", "notes"))
        self.assertIn("Repos: 1 in the catalog, 0 present here, 1 missing — "
                      "`BRAIN_DIR=brain-abacus uv run tools/repos/client-repos.py list --project notes`", self.lines("brief", "notes"))

    def test_brief_leaves_out_an_unreadable_catalog_with_a_warning(self) -> None:
        self.write("brain-acme/.data/client-repos.json", "{")
        result = self.run_tool("brief", "globex/migration")
        self.assertNotIn("Repos:", result.stdout)
        self.assertIn("brain-acme/.data/client-repos.json unreadable", result.stderr)

    def test_brief_defaults_keep_it_short(self) -> None:
        register = "".join(f"- [ ] **GLB-{number:03d}** — Jane Doe — Task {number}\n" for number in range(1, 15))
        self.write(f"{self.MIGRATION}/state/actions.md", f"# Actions — migration\n\n## Open\n{register}\n## Done\n")
        decisions = "".join(f"### Choice {number} (2026-10-{number:02d}, status: proposed)\n- **Decision:** d.\n\n" for number in range(1, 9))
        self.write(f"{self.MIGRATION}/state/decisions.md", f"# Decisions — migration\n\n## Proposed\n\n{decisions}## Accepted\n")
        self.write(f"{self.MIGRATION}/migration.md", "# Mission\n\n## Current state\n- " + "word " * 200 + "\n")
        data = self.data("brief", "globex/migration")
        self.assertEqual((len(data["actions"]["open"]), data["actions"]["more"]), (10, 4))  # 10 actions
        self.assertEqual((len(data["decisions"]["items"]), data["decisions"]["more"]), (5, 3))  # 5 decisions
        self.assertEqual(data["state"]["truncated_words"], 51)  # 150 words of state: 201 written

    def test_brief_resolves_the_project_as_action_does_and_lists_candidates(self) -> None:
        for project in ("globex / migration", "clients/globex/missions/migration", f"{self.MIGRATION}/state/actions.md", self.MIGRATION, "notes"):
            self.run_tool("brief", project)
        self.assertEqual(self.lines("brief", "notes")[0], "brain-abacus — notes — today 2026-10-25")
        unknown = self.run_tool("brief", "globex/migratio", code=1).stderr
        self.assertIn("unknown project globex/migratio: did you mean", unknown)
        self.assertIn(f"  brain-acme: globex / migration  ({self.MIGRATION})", unknown)
        self.assertNotIn("initech", unknown)
        unknown = self.run_tool("brief", "zzz", code=1).stderr
        self.assertIn("unknown project zzz: the projects are", unknown)
        self.assertIn("  brain-abacus: notes  (brain-abacus/projects/internal/notes)", unknown)
        self.project("brain-abacus/projects/internal/setup", actions=(("SET", " ", ""),))
        ambiguous = self.run_tool("brief", "setup", code=1).stderr
        self.assertIn("ambiguous project setup", ambiguous)
        self.assertIn("  brain-acme: setup  (brain-acme/projects/internal/setup)", ambiguous)
        self.assertIn("  brain-abacus: setup  (brain-abacus/projects/internal/setup)", ambiguous)
        self.assertEqual(self.lines("brief", "setup", "--brain", "brain-abacus")[0], "brain-abacus — setup — today 2026-10-25")
        self.assertIn("unknown project notes", self.run_tool("brief", "notes", "--brain", "brain-acme", code=1).stderr)
        self.assertIn("unknown brain brain-nope", self.run_tool("brief", "notes", "--brain", "brain-nope", code=1).stderr)

    def test_brief_also_takes_the_short_names_printed_by_map(self) -> None:
        first = "brain-acme — globex / migration — today 2026-10-25"
        self.assertEqual(self.lines("brief", "migration")[0], first)  # the project folder name
        self.assertEqual(self.lines("brief", "GLB")[0], first)  # the register ID prefix
        # an empty register resolves by the prefix its header reserves, as `map` prints it
        self.assertEqual(self.lines("brief", "SUP")[0], "brain-acme — globex / support — today 2026-10-25")
        self.assertIn("unknown project glb", self.run_tool("brief", "glb", code=1).stderr)

    # --- due ---

    def test_due_lists_late_then_upcoming_actions_by_project(self) -> None:
        self.assertEqual(self.lines("due"), [
            f"brain-acme — globex / migration  {self.MIGRATION}/state/actions.md",
            "  late  GLB-001 [ ] 2026-10-01  Jane Doe — Task 1",
            "  late  GLB-003 [/] 2026-10-24  Jane Doe — Task 3",
            "  due   GLB-002 [ ] 2026-10-25  Jane Doe — Task 2",
            "  due   GLB-004 [w] 2026-11-01  Jane Doe — Task 4",
            "2 late, 2 due by 2026-11-01 (7 day(s) from 2026-10-25)",
        ])
        self.assertEqual([line.split()[1] for line in self.lines("due", "--days", "6")[1:-1]], ["GLB-001", "GLB-003", "GLB-002"])
        self.assertEqual(self.lines("due", "--days", "0")[-1], "2 late, 1 due by 2026-10-25 (0 day(s) from 2026-10-25)")
        self.assertEqual(self.lines("due", "--brain", "brain-abacus"), ["0 late, 0 due by 2026-11-01 (7 day(s) from 2026-10-25)"])

    def test_due_covers_every_brain_and_its_json(self) -> None:
        self.project("brain-abacus/projects/internal/notes", actions=(("NOT", " ", "2026-10-26"), ("NOT", "x", "2026-10-01")))
        data = self.data("due")
        self.assertEqual(sorted(data), ["days", "late", "projects", "today", "until", "upcoming"])
        self.assertEqual((data["today"], data["days"], data["until"], data["late"], data["upcoming"]), ("2026-10-25", 7, "2026-11-01", 2, 3))
        self.assertEqual([(project["brain"], project["project"], [item["id"] for item in project["actions"]]) for project in data["projects"]],
                         [("brain-acme", "globex / migration", ["GLB-001", "GLB-003", "GLB-002", "GLB-004"]), ("brain-abacus", "notes", ["NOT-001"])])
        self.assertEqual(data["projects"][0]["actions"][0]["late"], True)
        self.assertIn("must be zero or positive", self.run_tool("due", "--days", "-1", code=1).stderr)

    # --- changes ---

    def make_history(self) -> None:
        state = "brain-acme/projects/clients/initech/missions/rollout/state"
        self.write(f"{state}/actions.md", (
            "# Actions — rollout\n\n## Open\n"
            "- [ ] **INI-001** — Jane Doe — Old and open ➕ 2026-09-01\n    - created: 2026-09-01 10:00\n"
            "- [/] **INI-002** — Jane Doe — Created this week ➕ 2026-10-22\n    - source: s\n    - created: 2026-10-22 09:30\n    - 23/10: a note\n"
            "\n## Done\n"
            "- [x] **INI-003** — Jane Doe — Old, closed this week ➕ 2026-09-02 ✅ 2026-10-23\n"
            "- [x] **INI-004** — Jane Doe — Closed without a date\n"
            "\n## Cancelled\n"
            "- [-] **INI-005** — Jane Doe — Dropped earlier ➕ 2026-09-03 ❌ 2026-10-10\n"
        ))
        self.write(f"{state}/actions-archive-2026.md", "# Actions archive 2026 — rollout\n\n## Done\n- [x] **INI-000** — Jane Doe — Archived closure ✅ 2026-09-20\n")
        self.write(f"{state}/decisions.md", (
            "# Decisions — rollout\n\n## Proposed\n\n### Pilot in one site (2026-10-21, status: proposed)\n- **Decision:** pilot.\n\n"
            "## Accepted\n\n### Freeze the scope (2026-09-05, status: accepted)\n- **Decision:** freeze.\n- **Accepted:** Jane Doe, 2026-10-24.\n\n"
            "## Rejected / superseded\n\n### Big bang (2026-09-04, status: rejected)\n- **Decision:** all at once.\n- **Rejected:** Jane Doe, 2026-09-06.\n"
        ))

    def test_changes_reads_timeline_actions_and_decisions_since_a_day(self) -> None:
        self.make_history()
        self.assertEqual(self.lines("changes", "--since", "2026-10-20"), [
            "brain-acme — globex / migration",
            "  2026-10-24  timeline  workshop",
            "  2026-10-20  timeline  kickoff",
            "brain-acme — initech / rollout",
            "  2026-10-25  timeline  page created",
            "  2026-10-24  settled   no. 2 [accepted] Freeze the scope",
            "  2026-10-23  closed    INI-003 [x] Jane Doe — Old, closed this week",
            "  2026-10-22  created   INI-002 [/] Jane Doe — Created this week",
            "  2026-10-21  decision  no. 1 [proposed] Pilot in one site",
            "brain-acme — setup",
            "  2026-10-25  timeline  page created",
            "brain-abacus — notes",
            "  2026-10-25  timeline  page created",
            "since 2026-10-20: 5 timeline, 1 created, 1 closed, 1 decision, 1 settled",
        ])

    def test_changes_accepts_a_number_of_days_and_reads_journals_and_archives(self) -> None:
        self.make_history()
        self.write(f"{self.MIGRATION}/journal/2026-09.md", "# Journal — 2026-09 — Migration\n\n- 2026-09-28 — audit\n- 2026-09-12 — scoping\n")
        data = self.data("changes", "--since", "40d", "--brain", "brain-acme")
        self.assertEqual((data["today"], data["since"]), ("2026-10-25", "2026-09-15"))
        events = {project["project"]: [(event["date"], event["kind"], event["text"].split(" ")[0]) for event in project["events"]]
                  for project in data["projects"]}
        self.assertEqual(events["globex / migration"], [
            ("2026-10-24", "timeline", "workshop"), ("2026-10-20", "timeline", "kickoff"), ("2026-10-02", "timeline", "preparation"),
            ("2026-10-02", "decision", "no."), ("2026-10-01", "decision", "no."), ("2026-09-28", "timeline", "audit"),
        ])
        self.assertEqual([event for event in events["initech / rollout"] if event[1] == "closed"],
                         [("2026-10-23", "closed", "INI-003"), ("2026-10-10", "closed", "INI-005"), ("2026-09-20", "closed", "INI-000")])
        audit = data["projects"][0]["events"][-1]
        self.assertEqual((audit["path"], audit["line"]), (f"{self.MIGRATION}/journal/2026-09.md", 3))
        self.assertEqual(sorted(data["projects"][0]), ["brain", "events", "more", "more_dates", "project", "ref"])
        self.assertEqual((data["projects"][0]["ref"], data["projects"][0]["more"], data["projects"][0]["more_dates"]), ("globex/migration", 0, None))
        self.assertEqual(self.lines("changes", "--since", "2026-12-01"), ["since 2026-12-01: nothing dated in the registers and the timelines"])
        self.assertIn("invalid --since last-week", self.run_tool("changes", "--since", "last-week", code=1).stderr)

    def make_busy_week(self) -> None:
        """An internal project `ops` whose register dates 27 creations, three a day from 2026-10-12 to 2026-10-20."""
        days = [f"2026-10-{day}" for day in range(12, 21)]
        lines = "".join(f"- [ ] **OPS-{number:03d}** — Jane Doe — Step {number} ➕ {days[(number - 1) // 3]}\n" for number in range(1, 28))
        self.write("brain-acme/projects/internal/ops/state/actions.md", f"# Actions — ops\n\n## Open\n{lines}\n## Done\n")

    def test_changes_shows_every_event_of_one_project(self) -> None:
        self.make_history()
        self.assertEqual(self.lines("changes", "--since", "2026-10-20", "--project", "initech/rollout"), [
            "brain-acme — initech / rollout",
            "  2026-10-25  timeline  page created",
            "  2026-10-24  settled   no. 2 [accepted] Freeze the scope",
            "  2026-10-23  closed    INI-003 [x] Jane Doe — Old, closed this week",
            "  2026-10-22  created   INI-002 [/] Jane Doe — Created this week",
            "  2026-10-21  decision  no. 1 [proposed] Pilot in one site",
            "since 2026-10-20: 1 timeline, 1 created, 1 closed, 1 decision, 1 settled",
        ])
        self.make_busy_week()
        text = self.lines("changes", "--since", "2026-10-01", "--project", "ops")
        self.assertEqual((len(text), text[1], text[-2]), (29, "  2026-10-20  created   OPS-025 [ ] Jane Doe — Step 25", "  2026-10-12  created   OPS-003 [ ] Jane Doe — Step 3"))
        self.assertNotIn("more", "\n".join(text))  # no cap for one project
        # an explicit --limit still cuts it, by whole days
        self.assertEqual(self.lines("changes", "--since", "2026-10-01", "--project", "ops", "--limit", "4")[-2:], [
            "  +24 more from 2026-10-12 to 2026-10-19; a higher --limit shows them", "since 2026-10-01: 27 created"])
        self.assertIn("unknown project nope", self.run_tool("changes", "--since", "7d", "--project", "nope", code=1).stderr)

    def test_changes_cuts_each_project_by_whole_days_and_says_how_to_see_the_rest(self) -> None:
        self.make_busy_week()
        text = self.lines("changes", "--since", "2026-10-01", "--brain", "brain-acme")
        ops = text[text.index("brain-acme — ops") + 1:text.index("brain-acme — setup")]
        self.assertEqual(len(ops), 19)  # six whole days of three events: a seventh would pass the cap of 20
        self.assertEqual((ops[0][:12], ops[-2][:12]), ("  2026-10-20", "  2026-10-15"))
        self.assertEqual(ops[-1], "  +9 more from 2026-10-12 to 2026-10-14; all of them: changes --since 2026-10-01 --project ops")
        # the latest day is kept whole even when it alone passes the cap; 0 shows none
        data = self.data("changes", "--since", "2026-10-01", "--limit", "2", "--brain", "brain-acme")
        ops = next(project for project in data["projects"] if project["project"] == "ops")
        self.assertEqual(([event["date"] for event in ops["events"]], ops["more"], ops["more_dates"], ops["ref"]),
                         (["2026-10-20"] * 3, 24, ["2026-10-12", "2026-10-19"], "ops"))
        data = self.data("changes", "--since", "2026-10-01", "--limit", "0", "--brain", "brain-acme")
        self.assertEqual({project["project"]: (len(project["events"]), project["more"]) for project in data["projects"]},
                         {"globex / migration": (0, 5), "initech / rollout": (0, 1), "ops": (0, 27), "setup": (0, 1)})
        self.assertIn("must be zero or positive", self.run_tool("changes", "--since", "7d", "--limit", "-1", code=1).stderr)
        # a project name two brains share: the hint names the folder, and the command it gives shows every event
        self.project("brain-abacus/projects/internal/ops", actions=(("OPX", " ", ""),))
        hint = [line for line in self.lines("changes", "--since", "2026-10-01") if line.startswith("  +9 more")]
        self.assertEqual(hint, ["  +9 more from 2026-10-12 to 2026-10-14; all of them: changes --since 2026-10-01 --project brain-acme/projects/internal/ops"])
        self.assertEqual(len(self.lines("changes", *hint[0].split("changes ")[1].split())), 29)

    # --- find ---

    def hits(self, *args: str) -> list[str]:
        """The output of `find`, one string per hit: `kind  path:line  excerpt` (the other lines as they are)."""
        found, kind, path = [], "", ""
        for line in self.lines("find", *args):
            if line.startswith("  :"):
                number, _, excerpt = line[3:].partition("  ")
                found.append(f"{kind:<10}  {path}:{number}  {excerpt}")
            elif line.split()[0] in {"action", "decision", "page", "person", "workstream", "note", "journal", "source"}:
                kind, path = line.split()
            else:
                found.append(line)
        return found

    def test_find_prints_each_file_once_then_its_hits(self) -> None:
        self.make_memory()
        rollout = self.ROLLOUT
        self.assertEqual(self.lines("find", "zurich"), [  # typed without the accent: the pages say Zürich
            f"action      {rollout}/state/actions.md",
            "  :7  INI-001 [ ] 14/10: site chosen with the Zürich team",
            f"decision    {rollout}/state/decisions.md",
            "  :6  no. 1 [proposed] **Context:** the Zürich site is ready.",
            f"page        {rollout}/rollout.md",
            "  :4  - Pilot in Zürich, then the other sites.",
            f"page        {rollout}/state/glossary.md",
            "  :3  - **Pilot**: the first site, Zürich.",
            f"workstream  {rollout}/workstreams/training.md",
            "  :4  The Zürich trainers start in November.",
            f"note        {rollout}/notes/2026-10-14-pilot-ideas.md",
            "  :3  Zürich first, then Geneva.",
            f"journal     {rollout}/journal/2026-09.md",  # most recent first
            "  :3  - 2026-09-28 — first contact about the Zürich pilot",
            f"journal     {rollout}/journal/2026-08.md",
            "  :3  - 2026-08-30 — proposal sent, Zürich mentioned",
            f"source      {self.KICKOFF}",
            "  :14  The pilot starts in Zürich on 3 November. The badge order waits for ticket REQ-0042.",
            f"source      {rollout}/sources/2026-10/index.md",
            "  :3  - 2026-10-13 · CR · [Kickoff](2026-10-13-cr-kickoff.md) — pilot in Zürich",
            f"source      {rollout}/sources/2026-09/2026-09-30-mail-badges.md",
            "  :10  Les badges seront commandés après le pilote à Zürich.  (+4 in this file)",  # one hit per file by default
        ])
        self.assertEqual(self.lines("find", "zurich", "--per-file", "3")[-4:], [
            f"source      {rollout}/sources/2026-09/2026-09-30-mail-badges.md",
            "  :10  Les badges seront commandés après le pilote à Zürich.",
            "  :14  - Zürich : 40 badges.",
            "  :15  - Zürich : livraison en novembre.  (+2 in this file)",
        ])
        # an identifier that only the minutes quote
        self.assertEqual(self.hits("req-0042"),
                         [f"source      {self.KICKOFF}:14  The pilot starts in Zürich on 3 November. The badge order waits for ticket REQ-0042."])

    def test_find_shows_one_line_per_action_or_decision_and_the_titles_first(self) -> None:
        self.make_memory()
        register = self.work / self.ROLLOUT / "state/actions.md"
        register.write_text(register.read_text(encoding="utf-8").replace(
            "    - 15/10: access requested\n", "    - 15/10: access requested, the cutover waits\n    - 16/10: cutover date asked\n"), encoding="utf-8")
        decisions = self.work / self.ROLLOUT / "state/decisions.md"
        decisions.write_text(decisions.read_text(encoding="utf-8").replace(
            "## Accepted\n", "### Keep Zürich as the reference (2026-10-14, status: proposed)\n- **Decision:** Zürich first.\n\n## Accepted\n"), encoding="utf-8")
        state = f"{self.ROLLOUT}/state"
        self.assertEqual(self.hits("cutover", "--in", "action", "--per-file", "0"), [
            f"action      {state}/actions.md:12  INI-004 [ ] Jane Doe / John Smith — Review the cutover checklist 📅 2026-10-30",  # its title: first
            f"action      {state}/actions.md:8  INI-001 [ ] 15/10: access requested, the cutover waits",  # one line for INI-001, not two
        ])
        self.assertEqual(self.lines("find", "cutover", "--in", "action"), [  # the default keeps the action the title names
            f"action      {state}/actions.md",
            "  :12  INI-004 [ ] Jane Doe / John Smith — Review the cutover checklist 📅 2026-10-30  (+1 in this file)",
        ])
        self.assertEqual(self.hits("zurich", "--in", "decision", "--per-file", "0"), [
            f"decision    {state}/decisions.md:9  no. 2 [proposed] Keep Zürich as the reference (2026-10-14)",
            f"decision    {state}/decisions.md:6  no. 1 [proposed] **Context:** the Zürich site is ready.",
        ])
        data = self.data("find", "zurich", "--in", "decision,action", "--per-file", "0")
        self.assertEqual((data["total"], data["kinds"], [hit["line"] for hit in data["hits"]]), (3, {"action": 1, "decision": 2}, [7, 9, 6]))
        self.assertEqual(sorted(data["hits"][0]), ["brain", "excerpt", "kind", "line", "more_in_file", "path"])  # one object per hit

    def test_find_project_keeps_one_project_folder(self) -> None:
        self.make_memory()
        self.write(f"{self.MIGRATION}/notes/2026-10-20-zurich.md", "# Trip\n\nVisit the Zürich office.\n")
        self.write("brain-abacus/projects/internal/notes/notes.md", "# notes\n\nA weekend in Zürich.\n")
        everywhere = {line.split()[1].split("/projects/")[1].split("/")[1 if "/clients/" in line else 0] for line in self.hits("zurich", "--per-file", "0")}
        self.assertEqual(everywhere, {"globex", "initech", "internal"})
        inside = self.hits("zurich", "--project", "initech/rollout", "--per-file", "0")
        self.assertEqual((len(inside), {line.split()[1].startswith(f"{self.ROLLOUT}/") for line in inside}), (15, {True}))
        self.assertEqual(self.hits("zurich", "--project", "migration"), [f"note        {self.MIGRATION}/notes/2026-10-20-zurich.md:3  Visit the Zürich office."])
        self.assertEqual(self.hits("weekend", "--project", "notes"), ["page        brain-abacus/projects/internal/notes/notes.md:3  A weekend in Zürich."])
        data = self.data("find", "zurich", "--project", "rollout", "--limit", "1")
        self.assertEqual((data["project"], data["brains"], data["total"]), (self.ROLLOUT, ["brain-acme"], 15))
        self.assertIsNone(self.data("find", "zurich")["project"])
        self.assertEqual(self.lines("find", "zurich", "--project", "rollout", "--limit", "1")[-1],
                         "+14 more: source 7, page 2, journal 2, decision 1, workstream 1, note 1 — narrow with --in, --per-file or --limit")
        self.assertEqual(self.lines("find", "geneva office", "--project", "rollout"), [(
            f'no match for "geneva office": 11 Markdown file(s) read in {self.ROLLOUT}, archives included; '
            "left out: the rest of the brains (drop --project), skills/ and hidden folders")])
        self.assertIn("unknown project nope", self.run_tool("find", "zurich", "--project", "nope", code=1).stderr)

    def test_find_matches_a_literal_text_without_case_or_accents(self) -> None:
        self.make_memory()
        migration = f"{self.MIGRATION}/state"
        self.assertEqual(self.hits("ZÜRICH TEAM"), [f"action      {self.ROLLOUT}/state/actions.md:7  INI-001 [ ] 14/10: site chosen with the Zürich team"])
        self.assertEqual(self.hits("glb-003"), [f"action      {migration}/actions.md:8  GLB-003 [/] Jane Doe — Task 3 📅 2026-10-24"])
        self.assertEqual(self.hits("keep the SCHEMA"), [f"decision    {migration}/decisions.md:5  no. 1 [proposed] Keep the schema (2026-10-01)"])
        self.assertEqual(self.hits("- **decision:** use it"), [f"decision    {migration}/decisions.md:9  no. 2 [proposed] **Decision:** use it."])
        self.assertEqual(self.hits("monitor"), ["note        brain-acme/inbox/inbox.md:6  buy a monitor"])  # the inbox is read too
        self.assertEqual(self.hits("client: globex"), ["page        brain-acme/projects/clients/globex/globex.md:1  # Client: Globex"])
        self.assertEqual(self.hits("actions — migration"), [f"action      {migration}/actions.md:1  # Actions — migration"])  # outside any action
        self.assertEqual(self.lines("find", "z.rich")[0][:8], "no match")  # a literal text, not a pattern
        self.assertEqual(self.lines("find", "zürich", "--in", "action", "team"), self.lines("find", "ZÜRICH TEAM"))  # several words: that phrase
        # spaces of any width and kind compare as one space
        self.write(f"{self.ROLLOUT}/notes/2026-10-15-budget.md", "# Budget\n\nBudget : 40 000 €  for   the pilot\n")
        self.assertEqual(self.hits("budget : 40 000 € for the"), [f"note        {self.ROLLOUT}/notes/2026-10-15-budget.md:3  Budget : 40 000 € for the pilot"])
        # typographic apostrophes, quotes and dashes compare as the ones of the keyboard
        self.write(f"{self.ROLLOUT}/notes/2026-10-15-budget.md", "# Budget\n\nL’équipe d’Initech — « pilote » validé\n")
        self.assertEqual(self.hits("l'equipe d'initech - \" pilote \" valide"),
                         [f"note        {self.ROLLOUT}/notes/2026-10-15-budget.md:3  L’équipe d’Initech — « pilote » validé"])

    def test_find_excerpt_keeps_the_action_id_and_the_match_in_160_characters(self) -> None:
        self.make_memory()
        register = self.work / self.ROLLOUT / "state/actions.md"
        long_note = "    - 16/10: " + "before " * 40 + "needle " + "after " * 40
        register.write_text(register.read_text(encoding="utf-8").replace("    - 15/10: access requested\n", f"    - 15/10: access requested\n{long_note}\n"), encoding="utf-8")
        hit = self.data("find", "Needle")["hits"][0]
        self.assertEqual((hit["kind"], hit["line"], len(hit["excerpt"]), hit["more_in_file"]), ("action", 9, 160, 0))
        self.assertTrue(hit["excerpt"].startswith("INI-001 [ ] …") and hit["excerpt"].endswith("…"), hit["excerpt"])
        before, _, after = hit["excerpt"].partition("needle")
        self.assertLess(abs(len(before) - len("INI-001 [ ] ") - len(after)), 3)  # the match sits in the middle of what follows the ID
        self.assertEqual(sorted(hit), ["brain", "excerpt", "kind", "line", "more_in_file", "path"])
        # the title of a long action line is cut, never its ID
        self.write(f"{self.ROLLOUT}/state/actions.md", "# Actions — rollout\n\n## Open\n- [w] **INI-009** — Jane Roe — " + "word " * 60 + "needle\n")
        self.assertRegex(self.lines("find", "needle")[1], r"^  :4  INI-009 \[w\] ….* needle$")

    def test_find_caps_the_hits_per_file_and_counts_what_is_left_by_kind(self) -> None:
        self.make_memory()
        text = self.hits("zurich", "--limit", "4")
        self.assertEqual([line.split()[0] for line in text[:4]], ["action", "decision", "page", "page"])
        self.assertEqual(text[4:], ["+11 more: source 7, journal 2, workstream 1, note 1 — narrow with --in, --project or --limit"])
        # a file cut by the limit: its hits left out are counted with the rest
        self.assertEqual(self.hits("zurich", "--limit", "12", "--per-file", "3")[12:], ["+3 more: source 3 — narrow with --in, --project or --limit"])
        everything = self.hits("zurich", "--per-file", "0")
        self.assertEqual((len(everything), sum("in this file" in line for line in everything)), (15, 0))
        data = self.data("find", "zurich", "--limit", "4")
        self.assertEqual(sorted(data), ["archived_projects_left_out", "archives_only", "brains", "files", "hits", "kinds", "more", "project", "scope", "term", "total"])
        self.assertEqual((data["term"], data["total"], len(data["hits"]), data["brains"], data["archives_only"]),
                         ("zurich", 15, 4, ["brain-acme", "brain-abacus"], False))
        self.assertEqual(data["kinds"], {"action": 1, "decision": 1, "page": 2, "workstream": 1, "note": 1, "journal": 2, "source": 7})
        self.assertEqual(data["more"], {"total": 11, "kinds": {"source": 7, "journal": 2, "workstream": 1, "note": 1}})
        self.assertEqual(self.data("find", "zurich")["hits"][-1]["more_in_file"], 4)
        self.assertIn("must be zero or positive", self.run_tool("find", "zurich", "--per-file", "-1", code=1).stderr)

    def test_find_in_keeps_some_kinds(self) -> None:
        self.make_memory()
        self.assertEqual([line.split()[0] for line in self.hits("zurich", "--in", "source,journal", "--limit", "3")],
                         ["journal", "journal", "source", "+6"])
        self.assertEqual({line.split()[0] for line in self.hits("zurich", "--in", "sources")}, {"source"})  # a plural is accepted
        self.assertEqual(self.hits("jane d.", "--in", "people"), ['person      brain-acme/people/jane-doe.md:5  aliases: ["Jane D.", JD, \'Jeanne Doe\']'])
        self.assertEqual(self.data("find", "zurich", "--in", "action, decision")["kinds"], {"action": 1, "decision": 1})
        self.assertEqual(self.lines("find", "zurich", "--in", "person"), [(
            'no match for "zurich" in person: 5 Markdown file(s) read in brain-acme, brain-abacus, archives included; '
            "left out: the other kinds (drop --in), 2 archived projects (--archived searches them), skills/ and hidden folders")])
        self.assertEqual(self.lines("find", "zurich", "--in", "person", "--archived"), [(
            'no match for "zurich" in person: 0 Markdown file(s) read in the archived projects of brain-acme, brain-abacus; '
            "left out: the other kinds (drop --in), the live projects (--all searches everything), skills/ and hidden folders")])
        unknown = self.run_tool("find", "zurich", "--in", "minutes", code=1).stderr
        self.assertIn("unknown kind minutes: choose among action, decision, page, person, workstream, note, journal, source", unknown)

    def test_find_reads_the_archives_on_request_or_when_nothing_else_matches(self) -> None:
        self.assertEqual(len(self.hits("task 1")), 4)  # migration, rollout, setup, notes: never the archived projects
        self.assertEqual(len(self.hits("task 1", "--all")), 6)  # everything, the two archived projects included
        self.assertEqual(len(self.hits("task 1", "--archived")), 2)  # the two archived projects only
        self.assertEqual(self.hits("task 1", "--brain", "brain-abacus"),
                         ["action      brain-abacus/projects/internal/notes/state/actions.md:6  NOT-001 [ ] Jane Doe — Task 1"])
        archived = "person      brain-acme/people/archive/john-roe.md:1  # John Roe"
        self.assertEqual(self.hits("john roe"), ['nothing in the live pages for "john roe"; in the archives:', archived])
        self.assertEqual(self.hits("john roe", "--all"), [archived])
        self.assertTrue(self.data("find", "john roe")["archives_only"])
        self.write(f"{self.MIGRATION}/state/actions-archive-2026.md",
                   "# Actions archive 2026 — migration\n\n## Done\n- [x] **GLB-000** — Jane Doe — First step ✅ 2026-08-01\n    - done: signed by the sponsor\n")
        self.assertEqual(self.hits("signed by the sponsor")[1],
                         f"action      {self.MIGRATION}/state/actions-archive-2026.md:5  GLB-000 [x] done: signed by the sponsor")
        self.assertEqual([line.split()[2] for line in self.hits("first step", "--all")], ["GLB-000"])
        # an archived project named by --project is read whole, with --archived or --all
        legacy = ["action      brain-acme/projects/clients/globex/missions/archive/legacy/state/actions.md:8  GLB-001 [x] Jane Doe — Task 1 📅 2026-01-05"]
        self.assertEqual(self.hits("task 1", "--project", "globex/legacy", "--archived"), legacy)
        self.assertEqual(self.hits("task 1", "--project", "globex/legacy", "--all"), legacy)

    def test_find_without_a_match_says_what_was_read(self) -> None:
        self.write("brain-acme/skills/demo/SKILL.md", "# Demo\n\nneedle in a skill\n")
        self.write("brain-acme/.data/notes.md", "needle in a hidden folder\n")
        self.write("brain-acme/projects/internal/setup/data.txt", "needle in a text file\n")
        pages = [path for path in self.work.rglob("*.md") if path.parent != self.work
                 and not {"skills", ".data"} & set(path.relative_to(self.work).parts)]
        parts = {path: path.relative_to(self.work).parts for path in pages}
        archived = [path for path in pages if parts[path][1] == "projects" and "archive" in parts[path][2:-1]]
        live = [path for path in pages if path not in archived]
        self.assertEqual(len(archived), 4)  # the page and the register of each of the two archived projects
        self.assertEqual(self.lines("find", "needle"), [(
            f'no match for "needle": {len(live)} Markdown file(s) read in brain-acme, brain-abacus, archives included; '
            "left out: 2 archived projects (--archived searches them), skills/ and hidden folders")])
        data = self.data("find", "Needle")
        self.assertEqual((data["term"], data["total"], data["hits"], data["kinds"], data["files"], data["scope"], data["archived_projects_left_out"]),
                         ("Needle", 0, [], {}, len(live), "live", 2))
        self.assertEqual(self.lines("find", "needle", "--brain", "brain-abacus"), [
            'no match for "needle": 4 Markdown file(s) read in brain-abacus, archives included; left out: skills/ and hidden folders'])
        self.assertEqual(self.lines("find", "needle", "--archived"), [(
            f'no match for "needle": {len(archived)} Markdown file(s) read in the archived projects of brain-acme, brain-abacus; '
            "left out: the live projects (--all searches everything), skills/ and hidden folders")])
        self.assertEqual(self.lines("find", "needle", "--all"), [(
            f'no match for "needle": {len(pages)} Markdown file(s) read in brain-acme, brain-abacus, archives and archived projects included; '
            "left out: skills/ and hidden folders")])
        self.assertEqual(self.lines("find", "needle", "--project", "globex/legacy", "--archived"), [(
            'no match for "needle": 2 Markdown file(s) read in brain-acme/projects/clients/globex/missions/archive/legacy, archives included; '
            "left out: the rest of the brains (drop --project), skills/ and hidden folders")])
        one = self.data("find", "needle", "--brain", "brain-acme")
        self.assertEqual(one["archived_projects_left_out"], 2)
        self.assertEqual(self.data("find", "needle", "--archived")["archived_projects_left_out"], 0)
        self.assertIn("empty search term", self.run_tool("find", "  ", code=1).stderr)

    def test_find_does_not_follow_links_out_of_the_brain(self) -> None:
        outside = self.write("outside/secret.md", "# needle outside the brain\n")
        (self.work / "brain-acme/people/linked.md").symlink_to(outside)
        (self.work / "brain-acme/projects/internal/linked").symlink_to(outside.parent, target_is_directory=True)
        self.assertEqual(self.lines("find", "needle")[0][:8], "no match")

    # --- archived projects: outside the context commands unless asked ---

    LEGACY = "brain-acme/projects/clients/globex/missions/archive/legacy"

    def make_archived_content(self) -> None:
        """The archived mission `globex/legacy` with an overdue open action, a recent closure, a decision, a timeline entry and a rare word."""
        self.write(f"{self.LEGACY}/state/actions.md", (
            "# Actions — legacy\n\n## Open\n- [ ] **GLB-090** — Jane Doe — Old overdue task 📅 2026-01-01\n\n"
            "## Done\n- [x] **GLB-091** — Jane Doe — Recent closure ✅ 2026-10-24\n\n## Cancelled\n"
        ))
        self.write(f"{self.LEGACY}/state/decisions.md",
                   "# Decisions — legacy\n\n## Proposed\n\n### Old choice (2026-10-01, status: proposed)\n- **Decision:** x.\n\n## Accepted\n")
        self.write(f"{self.LEGACY}/legacy.md", "# Mission legacy\n\n## Summary\nThe zebra project.\n\n## Timeline\n- 2026-10-24 — wrapped up\n")

    def test_brief_refuses_an_archived_project_and_says_how_to_read_or_restore_it(self) -> None:
        self.make_archived_content()
        error = self.run_tool("brief", "globex/legacy", code=1).stderr
        self.assertIn("project globex/legacy is archived (brain-acme/projects/clients/globex/missions/archive/legacy), outside the context commands: "
                      "`brief globex/legacy --archived` reads it; "
                      "`uv run tools/brain/brain-state.py unarchive brain-acme/projects/clients/globex/missions/archive/legacy --write` brings it back", error)
        self.assertIn("is archived", self.run_tool("brief", "old-tool", code=1).stderr)
        self.assertIn("is archived", self.run_tool("brief", "legacy", "--json", code=1).stderr)

    def test_brief_archived_reads_an_archived_project_and_points_to_commands_that_read_it_too(self) -> None:
        self.make_archived_content()
        data = self.data("brief", "globex/legacy", "--archived")
        self.assertEqual((data["project"], data["archived"]), ("globex / legacy", True))
        self.assertEqual(data["counts"]["open"], 1)
        self.assertEqual(self.data("brief", "globex/migration")["archived"], False)
        self.assertIn("[archived]", self.lines("brief", "globex/legacy", "--archived")[0])
        commands = {item["what"]: item["command"] for item in data["load_next"]}
        self.assertEqual(commands["actions"], "uv run tools/brain/action.py list --project globex/legacy --state all --table --archived")
        self.assertEqual(commands["decisions"], "uv run tools/brain/decision.py list --project globex/legacy --table --archived")
        # the commands run as printed
        for name, tool in (("actions", "action.py"), ("decisions", "decision.py")):
            command = commands[name].split()
            self.assertEqual(command[:3], ["uv", "run", f"tools/brain/{tool}"])
            result = subprocess.run([sys.executable, str(TOOL.with_name(tool)), *command[3:]], env=self.env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GLB-091" if name == "actions" else "Old choice", result.stdout)
        # a live project is not archived: no flag in its commands
        self.assertNotIn("--archived", " ".join(item["command"] for item in self.data("brief", "globex/migration")["load_next"]))

    def test_archived_projects_never_appear_in_due_changes_or_person(self) -> None:
        self.make_memory()
        self.make_archived_content()
        due = self.run_tool("due").stdout
        self.assertNotIn("GLB-090", due)
        self.assertNotIn("legacy", due)
        self.assertNotIn("GLB-090", json.dumps(self.data("due")))
        changes = self.run_tool("changes", "--since", "30d").stdout
        self.assertNotIn("GLB-091", changes)
        self.assertNotIn("wrapped up", changes)
        self.assertNotIn("legacy", changes)
        self.assertNotIn("GLB-091", json.dumps(self.data("changes", "--since", "30d")))
        person = self.run_tool("person", "Jane Doe").stdout
        self.assertNotIn("GLB-090", person)
        self.assertNotIn("legacy", person)
        self.assertNotIn("GLB-090", json.dumps(self.data("person", "Jane Doe")))
        self.assertIn("GLB-001", person)  # the live ones do

    def test_changes_refuses_an_archived_project_and_names_the_search_that_reads_it(self) -> None:
        self.make_archived_content()
        error = self.run_tool("changes", "--since", "30d", "--project", "globex/legacy", code=1).stderr
        self.assertIn("is archived (brain-acme/projects/clients/globex/missions/archive/legacy), outside the context commands: "
                      "`find TERM --archived --project globex/legacy` searches it; ", error)
        self.assertIn("unarchive", error)

    def test_brief_and_changes_refuse_a_mission_of_an_archived_client_and_name_the_client_folder(self) -> None:
        folder = "brain-acme/projects/clients/archive/soylent"
        self.write(f"{folder}/soylent.md", "# Client: Soylent\n")
        self.write(f"{folder}/missions/pilot/state/actions.md", "# Actions — pilot\n\n## Open\n- [ ] **SOY-001** — Jane Doe — Old 📅 2026-01-01\n")
        self.write(f"{folder}/missions/pilot/pilot.md", "# Mission pilot\n\n## Timeline\n- 2026-10-24 — wrapped up\n")
        for command in (("brief", "soylent/pilot"), ("changes", "--since", "30d", "--project", "soylent/pilot")):
            error = self.run_tool(*command, code=1).stderr
            self.assertIn(f"project soylent/pilot is archived ({folder}), outside the context commands: ", error)
            self.assertIn(f"`uv run tools/brain/brain-state.py unarchive {folder} --write` brings it back", error)
        self.assertEqual(self.data("brief", "soylent/pilot", "--archived")["project"], "soylent / pilot")
        self.assertNotIn("SOY-001", self.run_tool("due").stdout)

    def test_the_earlier_places_still_refuse_brief_and_changes(self) -> None:
        for folder, name in (("brain-acme/projects/clients/globex/archive/early", "globex/early"), ("brain-acme/projects/archive/early-tool", "early-tool")):
            self.write(f"{folder}/state/actions.md", "# Actions\n\n## Open\n")
            self.assertIn(f"is archived ({folder})", self.run_tool("brief", name, code=1).stderr)
            self.assertIn(f"unarchive {folder} --write", self.run_tool("changes", "--since", "30d", "--project", name, code=1).stderr)
            self.run_tool("brief", name, "--archived")

    def test_find_never_reads_archived_projects_by_default_and_has_no_fallback_into_them(self) -> None:
        self.make_archived_content()
        self.assertEqual(self.lines("find", "zebra"), [(
            'no match for "zebra": 18 Markdown file(s) read in brain-acme, brain-abacus, archives included; '
            "left out: 2 archived projects (--archived searches them), skills/ and hidden folders")])
        self.assertEqual(self.data("find", "zebra")["archived_projects_left_out"], 2)
        self.assertEqual(self.lines("find", "recent closure"), [(
            'no match for "recent closure": 18 Markdown file(s) read in brain-acme, brain-abacus, archives included; '
            "left out: 2 archived projects (--archived searches them), skills/ and hidden folders")])

    def test_find_without_a_live_match_falls_back_on_the_archives_of_live_content_not_on_archived_projects(self) -> None:
        self.make_archived_content()
        self.write("brain-acme/people/archive/zed-zebra.md", "# Zed Zebra\n")
        self.write(f"{self.MIGRATION}/state/actions-archive-2026.md", "# Actions archive 2026 — migration\n\n## Done\n- [x] **GLB-000** — Jane Doe — Zebra census ✅ 2026-08-01\n")
        out = self.lines("find", "zebra")
        self.assertEqual(out[0], 'nothing in the live pages for "zebra"; in the archives:')
        self.assertEqual(sorted(line.split()[1] for line in out if line.startswith(("person", "action"))),
                         ["brain-acme/people/archive/zed-zebra.md", f"{self.MIGRATION}/state/actions-archive-2026.md"])
        self.assertNotIn("legacy", "\n".join(out))
        data = self.data("find", "zebra")
        self.assertTrue(data["archives_only"])
        self.assertEqual((data["scope"], data["total"]), ("live", 2))

    def test_find_archived_searches_only_the_archived_projects(self) -> None:
        self.make_memory()
        self.make_archived_content()
        out = self.lines("find", "zebra", "--archived")
        self.assertEqual(out, [f"page        {self.LEGACY}/legacy.md", "  :4  The zebra project."])
        self.assertEqual({line.split()[1].split("/state")[0] for line in self.hits("task", "--archived")},
                         {"brain-acme/projects/clients/globex/missions/archive/legacy", "brain-acme/projects/internal/archive/old-tool"})
        self.assertEqual({line.split(":")[0].split()[-1].split("/state")[0] for line in self.hits("recent", "--archived")}, {self.LEGACY})
        data = self.data("find", "zebra", "--archived")
        self.assertEqual((data["scope"], data["total"], data["archived_projects_left_out"]), ("archived", 1, 0))
        # the live pages are not read
        self.assertEqual(len(self.hits("zurich", "--archived")), 1)
        self.assertTrue(self.hits("zurich", "--archived")[0].startswith('no match for "zurich"'))

    def test_find_all_searches_everything(self) -> None:
        self.make_memory()
        self.make_archived_content()
        self.write("brain-acme/people/archive/zed-zebra.md", "# Zed Zebra\n")
        out = self.lines("find", "zebra", "--all")
        self.assertEqual([line.split()[1] for line in out if not line.startswith(" ")], [f"{self.LEGACY}/legacy.md", "brain-acme/people/archive/zed-zebra.md"])
        self.assertEqual(self.data("find", "zebra", "--all")["scope"], "all")
        self.assertGreater(len(self.hits("zurich", "--all")), 0)

    def test_find_project_needs_archived_or_all_for_an_archived_project_and_refuses_it_for_a_live_one(self) -> None:
        self.make_archived_content()
        error = self.run_tool("find", "zebra", "--project", "globex/legacy", code=1).stderr
        self.assertIn("project globex/legacy is archived (", error)
        self.assertIn("`find zebra --archived --project globex/legacy` searches it", error)
        self.assertEqual(self.lines("find", "zebra", "--project", "globex/legacy", "--archived"), [f"page        {self.LEGACY}/legacy.md", "  :4  The zebra project."])
        self.assertEqual(self.lines("find", "zebra", "--project", "globex/legacy", "--all"), [f"page        {self.LEGACY}/legacy.md", "  :4  The zebra project."])
        refused = self.run_tool("find", "zebra", "--project", "globex/migration", "--archived", code=1).stderr
        self.assertIn("project globex/migration is not archived (brain-acme/projects/clients/globex/missions/migration): drop --archived", refused)
        self.assertEqual(self.lines("find", "task 1", "--project", "globex/migration", "--all")[0].split()[0], "action")

    def test_find_names_one_archived_project_in_the_singular(self) -> None:
        (self.work / "brain-acme/projects/internal/archive/old-tool").rename(self.work / "brain-acme/projects/internal/old-tool")
        self.assertIn("left out: 1 archived project (--archived searches it), skills/ and hidden folders", self.lines("find", "zebra")[0])
        self.assertNotIn("1 archived projects", self.lines("find", "zebra")[0])

    def test_section_reads_an_explicit_file_of_an_archived_project(self) -> None:
        self.make_archived_content()
        self.assertEqual(self.lines("section", f"{self.LEGACY}/legacy.md", "summary"), [
            f"{self.LEGACY}/legacy.md:3  ## Summary  (3 words)", "The zebra project."])
        self.assertEqual(self.lines("section", f"{self.LEGACY}/legacy.md")[0], f"{self.LEGACY}/legacy.md")

    # --- section ---

    def test_section_alone_prints_the_outline_of_a_page(self) -> None:
        self.make_memory()
        self.assertEqual(self.lines("section", self.KICKOFF), [
            self.KICKOFF,
            "front matter:",
            "  date: 2026-10-13",
            "  type: cr",
            "  title: Kickoff",
            '  participants: ["Jane Roe", "John Smith"]',
            "headings (line, title, words of the section):",
            "    8  # 2026-10-13 — Kickoff  (67 words)",
            "   12    ## Summary  (15 words)",
            "   16    ## Key points  (20 words)",  # with its sub-section
            "   21      ### Open questions  (6 words)",
            "   25    ## Décisions  (10 words)",
            "   29    ## Actions and follow-up  (8 words)",
            "total: 84 words",
        ])
        data = self.data("section", self.KICKOFF)
        self.assertEqual(sorted(data), ["front_matter", "headings", "path", "words"])
        self.assertEqual((data["path"], data["words"], data["front_matter"]["type"]), (self.KICKOFF, 84, "cr"))
        self.assertEqual(data["headings"][3], {"level": 3, "title": "Open questions", "line": 21, "words": 6})
        # a block list of the front matter is joined, a long value is cut, a `#` line in a code fence is not a heading
        page = self.write("brain-acme/projects/internal/setup/notes/2026-10-01-fence.md",
                          "---\ntags:\n  - one\n  - two\nabstract: " + "long " * 40 + "\n---\n\n## Real ##\n\n```sh\n# not a heading\n```\n\ntext\n")
        self.assertEqual(self.lines("section", str(page.relative_to(self.work))), [
            "brain-acme/projects/internal/setup/notes/2026-10-01-fence.md",
            "front matter:",
            "  tags: - one - two",
            "  abstract: " + ("long " * 40)[:99].rstrip() + "…",
            "headings (line, title, words of the section):",
            "    8  ## Real  (7 words)",
            "total: 58 words",
        ])
        self.assertEqual(self.lines("section", "brain-acme/AGENTS.md")[1:], ["headings (line, title, words of the section):", "    1  # test  (0 words)", "total: 2 words"])
        self.write("brain-acme/projects/internal/setup/notes/2026-10-01-fence.md", "### " + "long " * 30 + "\n\ntext\n")  # a long title is cut at 80 characters
        self.assertEqual(self.lines("section", "brain-acme/projects/internal/setup/notes/2026-10-01-fence.md")[2],
                         "    1  ### " + ("long " * 30)[:79].rstrip() + "…  (1 words)")

    def test_section_prints_the_section_named_by_its_heading(self) -> None:
        self.make_memory()
        summary = [f"{self.KICKOFF}:12  ## Summary  (15 words)", "The pilot starts in Zürich on 3 November. The badge order waits for ticket REQ-0042."]
        self.assertEqual(self.lines("section", self.KICKOFF, "Summary"), summary)
        self.assertEqual(self.lines("section", self.KICKOFF, "SUMMARY", "--words", "400"), summary)
        self.assertEqual(self.lines("section", self.KICKOFF, "key"), [  # no title is `key`: the one that starts with it, sub-section included
            f"{self.KICKOFF}:16  ## Key points  (20 words)", "- **Pilot:** one site first.", "- **Training:** Jane drafts the plan.", "",
            "### Open questions", "", "- Who pays for the badges?"])
        self.assertEqual(self.lines("section", self.KICKOFF, "follow")[0], f"{self.KICKOFF}:29  ## Actions and follow-up  (8 words)")  # a part of it
        self.assertEqual(self.lines("section", self.KICKOFF, "decisions")[0], f"{self.KICKOFF}:25  ## Décisions  (10 words)")  # without the accent
        self.assertEqual(self.lines("section", self.KICKOFF, "Actions", "and", "follow-up")[0], f"{self.KICKOFF}:29  ## Actions and follow-up  (8 words)")
        self.assertEqual(self.lines("section", self.KICKOFF, "--words", "400", "open", "questions")[0], f"{self.KICKOFF}:21  ### Open questions  (6 words)")
        several = self.run_tool("section", self.KICKOFF, "on", code=1).stderr.splitlines()
        self.assertEqual(several[0], f"several headings of {self.KICKOFF} match on: give more of the title, or its line ({self.KICKOFF}:LINE)")
        self.assertEqual(several[1:], ["   21      ### Open questions  (6 words)", "   25    ## Décisions  (10 words)", "   29    ## Actions and follow-up  (8 words)"])
        unknown = self.run_tool("section", self.KICKOFF, "budget", code=1).stderr.splitlines()
        self.assertEqual(unknown[0], f"no heading of {self.KICKOFF} matches budget; its headings (line, title, words of the section):")
        self.assertEqual(len(unknown), 7)
        # the exact title wins over the titles that start with it
        page = "brain-acme/projects/internal/setup/notes/2026-10-02-titles.md"
        self.write(page, "# Titles\n\n## Actions\n\nfirst\n\n## Actions and follow-up\n\nsecond\n")
        self.assertEqual(self.lines("section", page, "actions"), [f"{page}:3  ## Actions  (1 words)", "first"])
        self.assertIn("several headings", self.run_tool("section", page, "act", code=1).stderr)
        data = self.data("section", self.KICKOFF, "summary")
        self.assertEqual(data, {"path": self.KICKOFF, "line": 12, "level": 2, "heading": "Summary", "words": 15, "text": summary[1],
                                "from_line": 14, "skipped_words": 0, "truncated_words": 0, "truncated_at": None})

    def test_section_summary_stands_for_the_abstract_of_a_page(self) -> None:
        self.make_memory()
        mail = f"{self.ROLLOUT}/sources/2026-09/2026-09-30-mail-badges.md"
        self.assertEqual(self.lines("section", mail, "summary"), [f"{mail}:8  ## Résumé  (9 words)", "Les badges seront commandés après le pilote à Zürich."])
        page = "brain-acme/projects/internal/setup/notes/2026-10-03-abstracts.md"
        for body, expected in (
            ("## État actuel\n\nd\n\n## Current state\n\nc\n\n## En bref — 13/10\n\nb\n", "## Current state"),  # an exact title before one that starts with it
            ("## État actuel\n\nd\n\n## En bref — 13/10\n\nb\n", "## État actuel"),
            ("## Notes\n\nn\n\n## En bref — 13/10\n\nb\n\n## Executive summary\n\ne\n", "## En bref — 13/10"),
            ("## Notes\n\nn\n\n## Executive summary\n\ne\n", "## Executive summary"),
            ("## Résumé\n\nr\n\n## Summary\n\ns\n\n## Summary\n\nagain\n", "## Summary"),  # Summary first, and its first occurrence
        ):
            self.write(page, f"# Page\n\n{body}")
            self.assertEqual(self.lines("section", page, "summary")[0].split("  ")[1], expected)
        self.write(page, "# Page\n\n## Notes\n\nn\n")
        self.assertIn("no heading of", self.run_tool("section", page, "summary", code=1).stderr)

    def test_section_cuts_after_the_word_cap_and_says_where(self) -> None:
        self.make_memory()
        head = f"{self.KICKOFF}:16  ## Key points  (20 words)"
        self.assertEqual(self.lines("section", self.KICKOFF, "Key points", "--words", "6"), [  # a bullet left alone is not printed
            head, "- **Pilot:** one site first.", f"(truncated, 15 more words: {self.KICKOFF}:19)"])
        self.assertEqual(self.lines("section", self.KICKOFF, "Key points", "--words", "8"), [
            head, "- **Pilot:** one site first.", "- **Training:** Jane …", f"(truncated, 12 more words: {self.KICKOFF}:19)"])
        self.assertEqual(self.lines("section", self.KICKOFF, "Key points", "--words", "11"), [
            head, "- **Pilot:** one site first.", "- **Training:** Jane drafts the plan.", "", f"(truncated, 9 more words: {self.KICKOFF}:21)"])
        data = self.data("section", self.KICKOFF, "Key points", "--words", "8")
        self.assertEqual((data["truncated_words"], data["truncated_at"], data["text"].splitlines()[-1]), (12, 19, "- **Training:** Jane …"))
        self.assertEqual(self.lines("section", self.KICKOFF, "Summary", "--words", "0"), [f"{self.KICKOFF}:12  ## Summary  (15 words)", f"(truncated, 15 more words: {self.KICKOFF}:14)"])
        self.assertIn("must be zero or positive", self.run_tool("section", self.KICKOFF, "--words", "-1", code=1).stderr)

    def test_section_by_line_prints_the_section_that_holds_it(self) -> None:
        self.make_memory()
        questions = [f"{self.KICKOFF}:21  ### Open questions  (6 words)", "- Who pays for the badges?"]
        self.assertEqual(self.lines("section", f"{self.KICKOFF}:23"), questions)
        self.assertEqual(self.lines("section", f"{self.KICKOFF}:21"), questions)  # the heading itself
        self.assertEqual(self.lines("section", f"{self.KICKOFF}:19")[0], f"{self.KICKOFF}:16  ## Key points  (20 words)")
        self.assertEqual(self.lines("section", f"{self.KICKOFF}:10"), [f"{self.KICKOFF}:8  # 2026-10-13 — Kickoff  (67 words)"] + self.lines("section", self.KICKOFF, "kickoff")[1:])
        self.assertEqual(self.lines("section", f"{self.KICKOFF}:3"), [
            f"{self.KICKOFF}:1  (top of the page, above its first heading)  (13 words)",
            "---", "date: 2026-10-13", "type: cr", "title: Kickoff", 'participants: ["Jane Roe", "John Smith"]', "---"])
        self.assertIn(f"{self.KICKOFF} has 31 lines: no line 99", self.run_tool("section", f"{self.KICKOFF}:99", code=1).stderr)
        self.assertIn("a line (FILE:LINE) or a heading, not both", self.run_tool("section", f"{self.KICKOFF}:14", "summary", code=1).stderr)
        # what `find` prints goes straight to `section`
        where = self.hits("who pays")[0].split()[1]
        self.assertEqual(self.lines("section", where), questions)

    def test_section_by_line_starts_near_the_line_when_the_section_is_long(self) -> None:
        page = "brain-acme/projects/internal/setup/journal/2026-09.md"
        self.write(page, "# Log\n\n" + "".join(f"- entry {number} alpha beta gamma\n" for number in range(1, 41)))
        self.assertEqual(self.lines("section", f"{page}:30", "--words", "24"), [
            f"{page}:1  # Log  (240 words)",
            "(… 156 words above; from line 29)",
            "- entry 27 alpha beta gamma",  # one line above the line asked for
            "- entry 28 alpha beta gamma",
            "- entry 29 alpha beta gamma",
            "- entry 30 alpha beta gamma",
            f"(truncated, 60 more words: {page}:33)",
        ])
        data = self.data("section", f"{page}:30", "--words", "24")
        self.assertEqual((data["from_line"], data["skipped_words"], data["truncated_words"], data["truncated_at"]), (29, 156, 60, 33))
        # a line that ends in the first two thirds of the window: from the top, so that words follow it
        self.assertEqual(self.lines("section", f"{page}:4", "--words", "24"), [
            f"{page}:1  # Log  (240 words)", *(f"- entry {number} alpha beta gamma" for number in range(1, 5)), f"(truncated, 216 more words: {page}:7)"])
        # past them: the window starts a third of its words above the line
        self.assertEqual(self.lines("section", f"{page}:5", "--words", "24"), [
            f"{page}:1  # Log  (240 words)", "(… 6 words above; from line 4)", *(f"- entry {number} alpha beta gamma" for number in range(2, 6)),
            f"(truncated, 210 more words: {page}:8)"])
        # by default, 150 words around the line: 50 above it, and the rest of the section fits
        text = self.lines("section", f"{page}:30")
        self.assertEqual((len(text), text[1], text[2], text[-1]),
                         (23, "(… 114 words above; from line 22)", "- entry 20 alpha beta gamma", "- entry 40 alpha beta gamma"))
        self.assertEqual(self.data("section", f"{page}:3")["truncated_words"], 90)  # 150 of the 240 words
        self.assertEqual(len(self.lines("section", page, "log")), 41)  # a section named by its heading: 400 words by default
        self.assertEqual(self.lines("section", page, "log", "--words", "6"), [f"{page}:1  # Log  (240 words)", "- entry 1 alpha beta gamma", f"(truncated, 234 more words: {page}:4)"])

    def test_section_only_reads_a_markdown_file_inside_a_brain(self) -> None:
        self.make_memory()
        inside = self.KICKOFF.removeprefix("brain-acme/")
        first = f"{self.KICKOFF}:12  ## Summary  (15 words)"
        self.assertEqual(self.lines("section", inside, "summary", "--brain", "brain-acme")[0], first)  # from the brain
        self.assertEqual(self.lines("section", self.KICKOFF, "summary", "--brain", "brain-acme")[0], first)
        self.assertEqual(self.lines("section", str(self.work / self.KICKOFF), "summary")[0], first)  # a full path, inside a brain
        self.assertIn(f"no file {inside} in brain-abacus", self.run_tool("section", inside, "--brain", "brain-abacus", code=1).stderr)
        self.assertIn(f"{self.KICKOFF} is outside brain-abacus", self.run_tool("section", self.KICKOFF, "--brain", "brain-abacus", code=1).stderr)
        self.assertIn("no file brain-acme/nope.md in brain-acme, brain-abacus", self.run_tool("section", "brain-acme/nope.md", code=1).stderr)
        outside = self.write("outside/secret.md", "# Secret\n\nnot for the brains\n")
        (self.work / "brain-acme/people/linked.md").symlink_to(outside)
        for given in ("outside/secret.md", "brain-acme/../outside/secret.md", str(outside), "brain-acme/people/linked.md", "work-config.local.json"):
            result = self.run_tool("section", given, code=1)
            self.assertIn(f"{given} is outside brain-acme, brain-abacus: only the files of a brain are read", result.stderr)
            self.assertEqual(result.stdout, "")
        self.assertIn("brain-acme/.data/brain.json is not a Markdown file", self.run_tool("section", "brain-acme/.data/brain.json", code=1).stderr)
        # a file that several brains name the same way is not guessed
        result = self.run_tool("section", "AGENTS.md", code=1)
        self.assertIn("several files are named AGENTS.md", result.stderr)
        self.assertIn("  brain-acme/AGENTS.md\n  brain-abacus/AGENTS.md", result.stderr)

    # --- person ---

    def test_person_prints_who_someone_is_and_the_open_actions_they_carry(self) -> None:
        self.make_memory()
        self.assertEqual(self.lines("person", "jane-doe"), [
            "Jane Doe — Data lead, sponsor of the migration — Globex",
            "aliases: Jane D., JD, Jeanne Doe",
            "missions: migration, rollout",
            "- **Projects:** migration (sponsor), rollout (reviewer)",
            "## Role and scope",
            "Owns the data platform and signs off the plan.",
            "",
            "Open actions carried: 8, 2 late (today 2026-10-25)",
            "  late  GLB-001 [ ] 2026-10-01  Task 1  (globex / migration)",
            "  late  GLB-003 [/] 2026-10-24  Task 3  (globex / migration)",
            "        SET-001 [/] -           Task 1  (setup)",
            "        GLB-002 [ ] 2026-10-25  Task 2  (globex / migration)",
            "        INI-004 [ ] 2026-10-30  Review the cutover checklist  (initech / rollout, owner: Jane Doe / John Smith)",  # shared
            "        INI-005 [ ] -           Send the steering deck  (initech / rollout, owner: JD)",  # an alias
            "        NOT-001 [ ] -           Task 1  (notes)",  # in the other brain, which has no people page
            "        GLB-004 [w] 2026-11-01  Task 4  (globex / migration)",
            'Owner "Jane" is ambiguous between Jane Doe and Jane Roe: 1 open action(s), not counted above',
            "        INI-002 [/] 2026-11-03  Draft the training plan  (initech / rollout, owner: Jane)",
            "Page: brain-acme/people/jane-doe.md",
        ])

    def test_person_counts_a_first_name_only_when_one_people_page_bears_it(self) -> None:
        self.make_memory()

        def carried(name: str) -> list[str]:
            text = self.lines("person", name)
            return [line.split()[0] if line.split()[0] != "late" else line.split()[1] for line in text[text.index("") + 2:-1]]

        self.assertEqual(carried("Jane Roe"), ["INI-001", "INI-006", "Owner", "INI-002"])  # full name, `Zoé, then Jane Roe`, then the shared first name
        self.assertEqual(carried("John Smith"), ["INI-004", "INI-003"])  # `John` alone: the archived John Roe does not count
        self.assertEqual(carried("zoe-lefevre"), ["INI-006"])  # `Zoé` alone, written with its accent
        self.assertIn("Open actions carried: 2, 1 late (today 2026-10-25)", self.lines("person", "Jane Roe"))
        # a second John: the first name alone no longer says who
        self.write("brain-acme/people/john-brown.md", "---\nname: John Brown\naliases: [Johnny]\n---\n\n# John Brown\n")
        text = self.lines("person", "John Smith")
        self.assertEqual(text[text.index("") + 1:], [
            "Open actions carried: 1 (today 2026-10-25)",
            "        INI-004 [ ] 2026-10-30  Review the cutover checklist  (initech / rollout, owner: Jane Doe / John Smith)",
            'Owner "John" is ambiguous between John Brown and John Smith: 1 open action(s), not counted above',
            "        INI-003 [w] -           Order the badges  (initech / rollout, owner: John)",
            "Page: brain-acme/people/john-smith.md",
        ])
        self.assertEqual(self.lines("person", "john brown")[-4:-1], [
            "Open actions carried: none (today 2026-10-25)",
            'Owner "John" is ambiguous between John Brown and John Smith: 1 open action(s), not counted above',
            "        INI-003 [w] -           Order the badges  (initech / rollout, owner: John)",
        ])

    def test_person_is_found_by_slug_name_or_alias_without_case_or_accents(self) -> None:
        self.make_memory()
        for name, page in (("jane-doe", "jane-doe"), ("JANE DOE", "jane-doe"), ("doe", "jane-doe"), ("JD", "jane-doe"), ("jeanne", "jane-doe"),
                           ("Jane D.", "jane-doe"), ("john", "john-smith"), ("zoe", "zoe-lefevre"), ("ZOÉ LEFÈVRE", "zoe-lefevre"),
                           ("zozo", "zoe-lefevre"), ("lefevre zoe", "zoe-lefevre")):
            self.assertEqual(self.lines("person", name)[-1], f"Page: brain-acme/people/{page}.md", name)
        self.assertEqual(self.lines("person", "Jane", "--limit", "0", "Doe")[-1], "Page: brain-acme/people/jane-doe.md")  # no quotes needed
        several = self.run_tool("person", "jane", code=1).stderr.splitlines()
        self.assertEqual(several, ["several people are named jane: give the full name, or --brain NAME",
                                   "  brain-acme: Jane Doe  (brain-acme/people/jane-doe.md)", "  brain-acme: Jane Roe  (brain-acme/people/jane-roe.md)"])
        close = self.run_tool("person", "Jon Smyth", code=1).stderr.splitlines()
        self.assertEqual(close[:2], ["unknown person Jon Smyth: the closest names are", "  brain-acme: John Smith  (brain-acme/people/john-smith.md)"])
        self.assertEqual(close[-1], 'for an owner without a page: uv run tools/brain/action.py list --owner "Jon Smyth" --table')
        self.assertIn("  brain-acme: Jane Roe  (brain-acme/people/jane-roe.md)", self.run_tool("person", "roex", code=1).stderr)  # a name that starts the same
        self.assertIn("unknown person xyz: none of the 5 people pages has a close name", self.run_tool("person", "xyz", code=1).stderr)
        self.assertIn("none of the 0 people pages", self.run_tool("person", "jane doe", "--brain", "brain-abacus", code=1).stderr)
        # an archived page is used when no live page bears the name
        self.assertEqual(self.lines("person", "john roe")[-1], "Page: brain-acme/people/archive/john-roe.md (archived)")
        # the same person in two brains: the brain has to be named
        self.write("brain-abacus/people/jane-doe.md", "# Jane Doe\n\n- **Role:** friend\n")
        self.assertIn("  brain-abacus: Jane Doe  (brain-abacus/people/jane-doe.md)", self.run_tool("person", "jane doe", code=1).stderr)
        self.assertEqual(self.lines("person", "jane doe", "--brain", "brain-abacus"), [
            "Jane Doe", "- **Role:** friend", "", "Open actions carried: 1 (today 2026-10-25)", "        NOT-001 [ ] -           Task 1  (notes)",
            "Page: brain-abacus/people/jane-doe.md"])

    def test_person_counts_the_owner_of_a_brain_as_one_more_person(self) -> None:
        self.make_memory()
        self.write("brain-acme/.data/doctor.json", json.dumps({"owner": "Jane"}))
        # `Jane` alone is now the owner of the brain: neither Jane Doe nor Jane Roe, and no longer ambiguous
        self.assertEqual(self.lines("person", "jane"), [
            "Jane — owner of brain-acme, without a people page",
            "",
            "Open actions carried: 1 (today 2026-10-25)",
            "        INI-002 [/] 2026-11-03  Draft the training plan  (initech / rollout)",
            "Page: none",
        ])
        self.assertNotIn("ambiguous", self.run_tool("person", "jane-doe").stdout)
        self.assertEqual(self.lines("person", "jane roe")[-4:-1], [
            "Open actions carried: 2, 1 late (today 2026-10-25)",
            "  late  INI-001 [ ] 2026-10-20  Prepare the pilot site  (initech / rollout)",
            "        INI-006 [ ] -           Book the room  (initech / rollout, owner: Zoé, then Jane Roe)",
        ])
        self.write("brain-acme/me/about-me.md", "# About me\n\n## Professional identity\nOwner of the fixture.\n")
        data = self.data("person", "Jane")
        self.assertEqual((data["name"], data["owner_of"], data["path"], data["actions"]["total"], data["identity"]["text"]),
                         ("Jane", ["brain-acme"], "brain-acme/me/about-me.md", 1, "Jane — owner of brain-acme, without a people page"))
        self.assertEqual(self.lines("person", "jane")[-1], "Page: brain-acme/me/about-me.md (the owner's profile)")
        # a full name for the owner: a first name shared with a people page says no more who it is
        self.write("brain-acme/.data/doctor.json", json.dumps({"owner": "John Owner"}))
        text = self.lines("person", "john smith")
        self.assertEqual(text[text.index("") + 1:-1], [
            "Open actions carried: 1 (today 2026-10-25)",
            "        INI-004 [ ] 2026-10-30  Review the cutover checklist  (initech / rollout, owner: Jane Doe / John Smith)",
            'Owner "John" is ambiguous between John Smith and John Owner: 1 open action(s), not counted above',
            "        INI-003 [w] -           Order the badges  (initech / rollout, owner: John)",
        ])
        several = self.run_tool("person", "john", code=1).stderr
        self.assertIn("  brain-acme: John Owner  (owner of brain-acme, without a people page)", several)
        # an owner who has a people page is that page; the same owner of two brains is one person
        self.write("brain-acme/people/john-owner.md", "# John Owner\n")
        self.assertEqual(self.lines("person", "john owner")[-1], "Page: brain-acme/people/john-owner.md")
        self.write("brain-acme/.data/doctor.json", json.dumps({"owner": "Olga"}))
        self.write("brain-abacus/.data/doctor.json", json.dumps({"owner": "Olga"}))
        self.assertEqual(self.lines("person", "olga")[0], "Olga — owner of brain-acme, brain-abacus, without a people page")
        self.env["BRAIN_OWNER"] = "Zoé Lefèvre"  # the variable `action.py board` reads comes first
        self.assertIn("unknown person olga", self.run_tool("person", "olga", code=1).stderr)

    def test_person_caps_the_identity_and_the_actions(self) -> None:
        self.make_memory()
        self.assertEqual(self.lines("person", "john smith", "--words", "5")[:4], [
            "John Smith", "- **Role:** architect", "(truncated, 13 more words: brain-acme/people/john-smith.md:4)", ""])
        self.assertEqual(self.lines("person", "john smith")[:5], [  # no front matter: the title, the lines under it, the Context section
            "John Smith", "- **Role:** architect", "- **Team / project:** platform team", "## Context", "Joined the migration in October."])
        self.assertEqual(self.lines("person", "zoe")[:3], ["Zoé Lefèvre — Trainer", "aliases: Zoé L., Zozo", ""])  # a block list of aliases
        text = self.lines("person", "jane-doe", "--limit", "2")
        self.assertEqual(text[7:], [
            "Open actions carried: 8, 2 late (today 2026-10-25)",
            "  late  GLB-001 [ ] 2026-10-01  Task 1  (globex / migration)",
            "  late  GLB-003 [/] 2026-10-24  Task 3  (globex / migration)",
            "  +6 more",
            'Owner "Jane" is ambiguous between Jane Doe and Jane Roe: 1 open action(s), not counted above',
            "        INI-002 [/] 2026-11-03  Draft the training plan  (initech / rollout, owner: Jane)",
            "Page: brain-acme/people/jane-doe.md",
        ])
        self.assertIn("must be zero or positive", self.run_tool("person", "jane-doe", "--limit", "-1", code=1).stderr)

    def test_person_json_has_the_same_fields(self) -> None:
        self.make_memory()
        data = self.data("person", "jane-doe", "--limit", "1", "--words", "12")
        self.assertEqual(sorted(data), ["actions", "aliases", "ambiguous", "archived", "brain", "identity", "missions", "name", "organization",
                                        "owner_of", "path", "role", "today"])
        self.assertEqual((data["path"], data["owner_of"]), ("brain-acme/people/jane-doe.md", []))
        self.assertEqual((data["name"], data["role"], data["organization"], data["aliases"], data["missions"], data["archived"]),
                         ("Jane Doe", "Data lead, sponsor of the migration", "Globex", ["Jane D.", "JD", "Jeanne Doe"], ["migration", "rollout"], False))
        self.assertEqual(data["identity"], {"text": "Jane Doe — Data lead, sponsor of the migration — Globex\naliases: …",
                                            "truncated_words": 27, "truncated_at": None})  # cut in the front matter: no line to point at
        self.assertEqual((data["actions"]["total"], data["actions"]["late"], data["actions"]["more"]), (8, 2, 7))
        self.assertEqual(data["actions"]["items"], [{"id": "GLB-001", "state": " ", "due": "2026-10-01", "owner": "Jane Doe", "title": "Task 1",
                                                     "late": True, "project": "globex / migration"}])
        self.assertEqual([(group["owner"], group["between"], group["total"], group["more"], [item["id"] for item in group["items"]])
                          for group in data["ambiguous"]], [("Jane", ["Jane Doe", "Jane Roe"], 1, 0, ["INI-002"])])
        self.assertEqual(self.data("person", "john smith", "--words", "5")["identity"]["truncated_at"], 4)

    def test_context_commands_write_nothing(self) -> None:
        self.make_memory()

        def snapshot() -> list:
            return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.work.rglob("*"))
        before = snapshot()
        for args in (("brief", "globex/migration"), ("brief", "globex/migration", "--json"), ("due",), ("changes", "--since", "30d"),
                     ("find", "task", "--all"), ("find", "zurich"), ("find", "nowhere"), ("section", self.KICKOFF),
                     ("section", self.KICKOFF, "summary"), ("section", f"{self.KICKOFF}:14"), ("person", "jane-doe"), ("person", "john", "--json"),
                     ("map", "--archived"), ("map", "--all", "--json"), ("brief", "globex/legacy", "--archived"), ("find", "task", "--archived"),
                     ("find", "task", "--archived", "--project", "globex/legacy"), ("find", "nowhere", "--all", "--json")):
            self.run_tool(*args)
        self.assertEqual(snapshot(), before)


class BrainArchiveTest(unittest.TestCase):
    """`archive` and `unarchive`: a finished project or client moves whole, the links that follow it are rewritten, and it comes back as it was."""

    TODAY = BrainMapTest.TODAY
    GLOBEX = "brain-acme/projects/clients/globex"
    UMBRELLA = "brain-acme/projects/clients/umbrella"
    setUp, tearDown, write, make_brain, project = (BrainMapTest.setUp, BrainMapTest.tearDown, BrainMapTest.write,
                                                   BrainMapTest.make_brain, BrainMapTest.project)
    make_acme, make_abacus = BrainMapTest.make_acme, BrainMapTest.make_abacus

    def make_links(self) -> None:
        """Two finished missions of globex that link to each other, a client page that links to both, a finished client (umbrella) with two
        missions, an internal project and a people page that link into each other, a client with no archive/, one project in each earlier place."""
        globex = self.GLOBEX
        self.write(f"{globex}/missions/migration/journal/2026-09.md", "# Journal — 2026-09 — migration\n")
        self.write(f"{globex}/globex.md", (
            "# Client: Globex\n\n- [old](./missions/../missions/old/old.md#timeline)\n- [old short](missions/old/old.md)\n"
            "- [dir](missions/old/)\n- [live](missions/live/live.md)\n- `[code](missions/old/old.md)`\n\n```\n[fenced](missions/old/old.md)\n```\n\n"
            "Plain mention: projects/clients/globex/missions/old is done.\n"))
        self.project(f"{globex}/missions/old", actions=(("OLD", "x", ""), ("OLD", "-", "")),
                     page="# old\n\n## Timeline\n- 2026-10-01 — x\n\nSee [live](../live/live.md), [self](old.md#timeline), [src](sources/a.md), "
                          "[client](../../globex.md) and [client2](./../../globex.md). Code: `[live](../live/live.md)`.\n")
        self.write(f"{globex}/missions/old/sources/a.md", "# a\n\n[back](../old.md) [live](../../live/live.md)\n")
        self.project(f"{globex}/missions/live", actions=(("LIV", "x", ""),),
                     page="# live\n\n## Timeline\n- 2026-10-01 — x\n\n[old](../old/old.md) [old2](../old/sources/a.md#top)\n")
        self.write("brain-acme/.data/client-repos.json", '{"path": "projects/clients/globex/missions/old"}')
        self.write("brain-acme/projects/internal/archive/README.md", "# archive\n")
        self.project("brain-acme/projects/internal/tool", actions=(("TOO", "x", ""),),
                     page="# tool\n\n[arch](../archive/old-tool/old-tool.md) [setup](../setup/setup.md) [umbrella](../../clients/umbrella/umbrella.md) "
                          "[alpha](../../clients/umbrella/missions/alpha/alpha.md#timeline)\n")
        self.write("brain-acme/notes.md", "[tool](projects/internal/tool/tool.md) [actions](projects/internal/tool/state/actions.md)\n")
        self.project("brain-acme/projects/clients/initech/missions/pilot", actions=(("INI", "x", ""),),
                     page="# pilot\n\n[rollout](../rollout/rollout.md)\n")
        # a finished client, its two missions, an internal project and a person that link into each other
        umbrella = self.UMBRELLA
        self.write(f"{umbrella}/umbrella.md", ("# Client: Umbrella\n\n- [alpha](missions/alpha/alpha.md)\n- [beta](./missions/../missions/beta/beta.md#timeline)\n"
                                              "- [tool](../../internal/tool/tool.md)\n- [tool2](./../../internal/tool/tool.md)\n- [dir](missions/)\n"
                                              "- [web](https://example.com/a.md) [anchor](#top)\n"))
        self.project(f"{umbrella}/missions/alpha", actions=(("UMB", "x", ""),),
                     page="# alpha\n\n## Timeline\n- 2026-10-01 — x\n\n[beta](../beta/beta.md) [tool](../../../../internal/tool/tool.md) "
                          "[person](../../../../../people/sam-lee.md) [client](../../umbrella.md)\n")
        self.project(f"{umbrella}/missions/beta", actions=(("UMB", "x", ""),), page="# beta\n\n## Timeline\n- 2026-10-01 — x\n\n[alpha](../alpha/alpha.md)\n")
        self.write("brain-acme/people/sam-lee.md", "# Sam Lee\n\n[alpha](../projects/clients/umbrella/missions/alpha/alpha.md) "
                                                   "[client](../projects/clients/umbrella/umbrella.md#top)\n")
        # one project in each earlier place
        self.project(f"{globex}/archive/early", actions=(("EAR", "x", ""),),
                     page="# early\n\n[client](../../globex.md) [live](../../missions/live/live.md)\n")
        self.project("brain-acme/projects/archive/legacy-tool", actions=(("LEG", "x", ""),),
                     page="# legacy-tool\n\n[setup](../../internal/setup/setup.md)\n")

    def run_tool(self, *args: str, code: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def run_json(self, *args: str, code: int = 0) -> dict:
        return json.loads(self.run_tool(*args, "--json", code=code).stdout)

    def snapshot(self) -> tuple[dict, set]:
        files = {str(path.relative_to(self.work)): path.read_bytes() for path in self.work.rglob("*") if path.is_file()}
        return files, {str(path.relative_to(self.work)) for path in self.work.rglob("*") if path.is_dir()}

    def read(self, relative: str) -> str:
        return (self.work / relative).read_text(encoding="utf-8")

    def test_dry_run_prints_the_move_and_each_link_to_rewrite_and_writes_nothing(self) -> None:
        self.make_links()
        before = self.snapshot()
        out = self.run_tool("archive", "globex/old").stdout.splitlines()
        globex = self.GLOBEX
        self.assertEqual(out[0], "archive globex / old (brain-acme) — dry run: nothing is moved, --write applies it")
        self.assertEqual(out[1], f"  move  {globex}/missions/old  →  {globex}/missions/archive/old")
        self.assertEqual(out[2], "  links: 9 to rewrite in 4 file(s)")
        self.assertEqual(out[3:12], [
            f"    {globex}/globex.md:3  ./missions/../missions/old/old.md#timeline  →  ./missions/../missions/archive/old/old.md#timeline",
            f"    {globex}/globex.md:4  missions/old/old.md  →  missions/archive/old/old.md",
            f"    {globex}/globex.md:5  missions/old/  →  missions/archive/old/",
            f"    {globex}/missions/live/live.md:6  ../old/old.md  →  ../archive/old/old.md",
            f"    {globex}/missions/live/live.md:6  ../old/sources/a.md#top  →  ../archive/old/sources/a.md#top",
            f"    {globex}/missions/archive/old/old.md:6  ../live/live.md  →  ../../live/live.md",
            f"    {globex}/missions/archive/old/old.md:6  ../../globex.md  →  ../../../globex.md",
            f"    {globex}/missions/archive/old/old.md:6  ./../../globex.md  →  .././../../globex.md",
            f"    {globex}/missions/archive/old/sources/a.md:3  ../../live/live.md  →  ../../../live/live.md",
        ])
        self.assertEqual(out[12], f"  not links, left as they are: {globex}/globex.md (1 mention), brain-acme/.data/client-repos.json (1 mention)")
        self.assertEqual(len(out), 13)  # no link check on a dry run
        data = self.run_json("archive", "globex/old")
        self.assertEqual((data["command"], data["kind"], data["write"], data["moved"], data["files_changed"], data["link_check"]),
                         ("archive", "mission", False, False, 4, None))
        self.assertEqual((data["from"], data["to"], data["created_dirs"], data["removed_dirs"]),
                         (f"{globex}/missions/old", f"{globex}/missions/archive/old", [], []))  # globex has a missions/archive/ already
        self.assertEqual(data["mentions_left"], [{"file": f"{globex}/globex.md", "count": 1}, {"file": "brain-acme/.data/client-repos.json", "count": 1}])
        self.assertEqual(data["links"][0], {"file": f"{globex}/globex.md", "line": 3, "from": "./missions/../missions/old/old.md#timeline",
                                            "to": "./missions/../missions/archive/old/old.md#timeline"})
        self.assertEqual(self.snapshot(), before)

    def test_write_moves_the_folder_rewrites_the_links_out_and_in_and_checks_them(self) -> None:
        self.make_links()
        out = self.run_tool("archive", "globex/old", "--write").stdout.splitlines()
        self.assertEqual(out[0], "archived globex / old (brain-acme)")
        self.assertEqual(out[2], "  links: 9 rewritten in 4 file(s)")
        self.assertRegex(out[-1], r"^  link check of brain-acme: exit 0 — dead 0 \(md\), 0 \(wiki\), cross-brain 0, unverified local 0$")
        globex = self.GLOBEX
        self.assertFalse((self.work / f"{globex}/missions/old").exists())
        self.assertTrue((self.work / f"{globex}/missions/archive/old/state/actions.md").is_file())
        self.assertTrue((self.work / f"{globex}/missions/archive/old/sources/a.md").is_file())
        self.assertFalse((self.work / f"{globex}/archive/old").exists())  # nothing is written in the earlier place
        # outside links: form kept (an archive segment inserted), anchor and trailing slash kept; code spans and fences left alone
        client = self.read(f"{globex}/globex.md")
        self.assertIn("- [old](./missions/../missions/archive/old/old.md#timeline)\n- [old short](missions/archive/old/old.md)\n- [dir](missions/archive/old/)\n", client)
        self.assertIn("- [live](missions/live/live.md)\n- `[code](missions/old/old.md)`\n\n```\n[fenced](missions/old/old.md)\n```\n", client)
        self.assertIn("Plain mention: projects/clients/globex/missions/old is done.", client)
        self.assertIn("[old](../archive/old/old.md) [old2](../archive/old/sources/a.md#top)", self.read(f"{globex}/missions/live/live.md"))
        # links inside the folder, now one level deeper: the ones that point out are rewritten, shortest stays shortest, the form is kept otherwise
        moved = self.read(f"{globex}/missions/archive/old/old.md")
        self.assertIn("[live](../../live/live.md), [self](old.md#timeline), [src](sources/a.md), [client](../../../globex.md) and "
                      "[client2](.././../../globex.md).", moved)
        self.assertIn("Code: `[live](../live/live.md)`.", moved)  # a code span is left alone, inside as outside
        self.assertEqual(self.read(f"{globex}/missions/archive/old/sources/a.md"), "# a\n\n[back](../old.md) [live](../../../live/live.md)\n")
        self.assertEqual(self.read("brain-acme/.data/client-repos.json"), '{"path": "projects/clients/globex/missions/old"}')  # not links
        # the mission reads as an archived project afterwards
        self.assertIn("is archived", self.run_tool("brief", "globex/old", code=1).stderr)
        self.run_tool("brief", "globex/old", "--archived")

    def test_write_json_reports_the_link_check(self) -> None:
        self.make_links()
        data = self.run_json("archive", "globex/old", "--write")
        self.assertEqual((data["write"], data["moved"], data["files_changed"], len(data["links"])), (True, True, 4, 9))
        self.assertEqual(data["link_check"]["exit"], 0)
        self.assertEqual(data["link_check"]["counts"]["dead (md)"], 0)
        self.assertGreater(data["link_check"]["counts"]["md links"], 0)

    def test_archive_creates_the_missions_archive_folder_and_unarchive_removes_it_when_empty(self) -> None:
        self.make_links()
        pilot = "brain-acme/projects/clients/initech/missions"
        before = self.snapshot()
        self.assertFalse((self.work / f"{pilot}/archive").exists())
        data = self.run_json("archive", "initech/pilot", "--write")
        self.assertEqual((data["kind"], data["created_dirs"], data["removed_dirs"]), ("mission", [f"{pilot}/archive"], []))
        self.assertTrue((self.work / f"{pilot}/archive/pilot/pilot.md").is_file())
        back = self.run_json("unarchive", "initech/pilot", "--write")
        self.assertEqual((back["created_dirs"], back["removed_dirs"]), ([], [f"{pilot}/archive"]))
        self.assertFalse((self.work / f"{pilot}/archive").exists())
        self.assertEqual(self.snapshot(), before)

    def test_text_mentions_the_folders_created_and_removed(self) -> None:
        self.make_links()
        pilot = "brain-acme/projects/clients/initech/missions"
        self.assertIn(f"  created  {pilot}/archive", self.run_tool("archive", "initech/pilot", "--write").stdout.splitlines())
        self.assertIn(f"  removed  {pilot}/archive (empty)", self.run_tool("unarchive", "initech/pilot", "--write").stdout.splitlines())

    def test_unarchive_is_the_exact_inverse_of_archive_for_a_mission(self) -> None:
        self.make_links()
        before = self.snapshot()
        self.run_tool("archive", "globex/old", "--write")
        self.assertNotEqual(self.snapshot(), before)
        out = self.run_tool("unarchive", "globex/old", "--write").stdout.splitlines()
        self.assertEqual(out[0], "unarchived globex / old (brain-acme)")
        self.assertEqual(self.snapshot(), before)  # every file byte for byte, the non-shortest links included
        self.assertIn("./missions/../missions/old/old.md#timeline", self.read(f"{self.GLOBEX}/globex.md"))
        self.assertIn("./../../globex.md", self.read(f"{self.GLOBEX}/missions/old/old.md"))
        self.assertTrue((self.work / f"{self.GLOBEX}/missions/archive").is_dir())  # globex already had a missions/archive/ folder: it stays

    def test_internal_projects_move_between_internal_and_internal_archive(self) -> None:
        self.make_links()
        before = self.snapshot()
        data = self.run_json("archive", "tool", "--write")
        self.assertEqual((data["kind"], data["from"], data["to"], data["created_dirs"], data["link_check"]["exit"]),
                         ("internal", "brain-acme/projects/internal/tool", "brain-acme/projects/internal/archive/tool", [], 0))
        self.assertEqual(self.read("brain-acme/notes.md"),
                         "[tool](projects/internal/archive/tool/tool.md) [actions](projects/internal/archive/tool/state/actions.md)\n")
        self.assertEqual(self.read("brain-acme/projects/internal/archive/tool/tool.md"), (
            "# tool\n\n[arch](../old-tool/old-tool.md) [setup](../../setup/setup.md) [umbrella](../../../clients/umbrella/umbrella.md) "
            "[alpha](../../../clients/umbrella/missions/alpha/alpha.md#timeline)\n"))
        self.assertIn("[tool](../../../../internal/archive/tool/tool.md)", self.read(f"{self.UMBRELLA}/missions/alpha/alpha.md"))
        back = self.run_json("unarchive", "tool", "--write")
        self.assertEqual((back["kind"], back["from"], back["to"], back["removed_dirs"]),
                         ("internal", "brain-acme/projects/internal/archive/tool", "brain-acme/projects/internal/tool", []))
        self.assertTrue((self.work / "brain-acme/projects/internal/archive/README.md").is_file())  # internal/archive/ with a README is never removed
        self.assertEqual(self.snapshot(), before)

    def test_a_whole_client_moves_with_its_missions_and_comes_back_byte_for_byte(self) -> None:
        self.make_links()
        before = self.snapshot()
        umbrella = self.UMBRELLA
        out = self.run_tool("archive", "clients/umbrella").stdout.splitlines()
        self.assertEqual(out[0], "archive client umbrella (brain-acme) — dry run: nothing is moved, --write applies it")
        self.assertEqual(out[1], f"  move  {umbrella}  →  brain-acme/projects/clients/archive/umbrella")
        self.assertRegex(out[2], r"^  links: \d+ to rewrite in \d+ file\(s\)$")
        self.assertEqual(self.snapshot(), before)  # a dry run creates nothing
        data = self.run_json("archive", "clients/umbrella", "--write")
        self.assertEqual((data["command"], data["kind"], data["project"], data["from"], data["to"]),
                         ("archive", "client", "client umbrella", umbrella, "brain-acme/projects/clients/archive/umbrella"))
        self.assertEqual((data["created_dirs"], data["removed_dirs"], data["link_check"]["exit"]), (["brain-acme/projects/clients/archive"], [], 0))
        archived = "brain-acme/projects/clients/archive/umbrella"
        self.assertFalse((self.work / umbrella).exists())
        for name in ("umbrella.md", "missions/alpha/alpha.md", "missions/beta/beta.md", "missions/alpha/state/actions.md"):
            self.assertTrue((self.work / archived / name).is_file(), name)
        # links inside that stay inside are untouched, the ones that point out are rewritten, one level deeper
        self.assertEqual(self.read(f"{archived}/umbrella.md"), (
            "# Client: Umbrella\n\n- [alpha](missions/alpha/alpha.md)\n- [beta](./missions/../missions/beta/beta.md#timeline)\n"
            "- [tool](../../../internal/tool/tool.md)\n- [tool2](.././../../internal/tool/tool.md)\n- [dir](missions/)\n"
            "- [web](https://example.com/a.md) [anchor](#top)\n"))
        self.assertEqual(self.read(f"{archived}/missions/alpha/alpha.md"), (
            "# alpha\n\n## Timeline\n- 2026-10-01 — x\n\n[beta](../beta/beta.md) [tool](../../../../../internal/tool/tool.md) "
            "[person](../../../../../../people/sam-lee.md) [client](../../umbrella.md)\n"))
        self.assertEqual(self.read("brain-acme/people/sam-lee.md"), (
            "# Sam Lee\n\n[alpha](../projects/clients/archive/umbrella/missions/alpha/alpha.md) "
            "[client](../projects/clients/archive/umbrella/umbrella.md#top)\n"))
        self.assertIn("[umbrella](../../clients/archive/umbrella/umbrella.md) [alpha](../../clients/archive/umbrella/missions/alpha/alpha.md#timeline)",
                      self.read("brain-acme/projects/internal/tool/tool.md"))
        self.assertIn("is archived", self.run_tool("brief", "umbrella/alpha", code=1).stderr)
        back = self.run_json("unarchive", "clients/umbrella", "--write")
        self.assertEqual((back["kind"], back["from"], back["to"], back["created_dirs"], back["removed_dirs"], back["link_check"]["exit"]),
                         ("client", "brain-acme/projects/clients/archive/umbrella", umbrella, [], ["brain-acme/projects/clients/archive"], 0))
        self.assertEqual(self.snapshot(), before)  # the whole tree, byte for byte, and clients/archive/ is gone again

    def test_archiving_the_last_live_mission_of_a_client_does_not_archive_the_client(self) -> None:
        self.make_links()
        for mission in ("alpha", "beta"):
            data = self.run_json("archive", f"umbrella/{mission}", "--write")
            self.assertEqual((data["kind"], data["to"]), ("mission", f"{self.UMBRELLA}/missions/archive/{mission}"))
        self.assertTrue((self.work / f"{self.UMBRELLA}/umbrella.md").is_file())
        self.assertFalse((self.work / "brain-acme/projects/clients/archive").exists())
        self.assertEqual({client["name"]: client["archived"] for client in self.run_json("map")["brains"][0]["clients"]},
                         {"globex": False, "initech": False, "umbrella": False})  # umbrella, with no live mission, is still a live client

    def test_the_three_kinds_archived_then_unarchived_in_reverse_order_give_the_tree_back_byte_for_byte(self) -> None:
        self.make_links()
        before = self.snapshot()
        steps = (("umbrella/alpha", "mission"), ("tool", "internal"), ("clients/umbrella", "client"))
        for project, kind in steps:
            data = self.run_json("archive", project, "--write")
            self.assertEqual((data["kind"], data["link_check"]["exit"], data["link_check"]["counts"]["dead (md)"]), (kind, 0, 0), project)
        self.assertFalse((self.work / self.UMBRELLA).exists())
        self.assertTrue((self.work / "brain-acme/projects/clients/archive/umbrella/missions/archive/alpha/alpha.md").is_file())
        self.assertIn("(../../../../../../internal/archive/tool/tool.md)",  # alpha, in a client archived and in an archived mission
                      self.read("brain-acme/projects/clients/archive/umbrella/missions/archive/alpha/alpha.md"))
        for project, kind in reversed(steps):
            wanted = "clients/umbrella" if kind == "client" else project
            data = self.run_json("unarchive", wanted, "--write")
            self.assertEqual((data["kind"], data["link_check"]["exit"], data["link_check"]["counts"]["dead (md)"]), (kind, 0, 0), project)
        self.assertEqual(self.snapshot(), before)

    def test_the_client_internal_and_folder_forms_name_what_to_archive(self) -> None:
        self.make_links()
        self.write("brain-acme/projects/clients/solo/solo.md", "# Client: Solo\n\n[globex](../globex/globex.md)\n")  # a client with no register
        self.write("brain-acme/projects/internal/bare/bare.md", "# bare\n\n[tool](../tool/tool.md)\n")  # a project with no register
        data = self.run_json("archive", "clients/solo", "--write")
        self.assertEqual((data["kind"], data["project"], data["to"]), ("client", "client solo", "brain-acme/projects/clients/archive/solo"))
        self.assertEqual(self.read("brain-acme/projects/clients/archive/solo/solo.md"), "# Client: Solo\n\n[globex](../../globex/globex.md)\n")
        data = self.run_json("archive", "brain-acme/projects/internal/bare", "--write")  # a folder path, from the Work root: it moves too
        self.assertEqual((data["kind"], data["project"], data["to"]), ("internal", "bare", "brain-acme/projects/internal/archive/bare"))
        self.assertEqual(self.read("brain-acme/projects/internal/archive/bare/bare.md"), "# bare\n\n[tool](../../tool/tool.md)\n")
        for path, kind, to in ((f"{self.GLOBEX}/missions/old", "mission", f"{self.GLOBEX}/missions/archive/old"),
                               (str(self.work / "brain-acme/projects/internal/tool"), "internal", "brain-acme/projects/internal/archive/tool"),
                               ("projects/clients/umbrella", "client", "brain-acme/projects/clients/archive/umbrella")):
            # a folder path as `brain/projects/...` from the Work root, absolute, or from inside a brain (with --brain)
            args = ("archive", path, "--brain", "brain-acme") if path.startswith("projects/") else ("archive", path)
            data = self.run_json(*args)
            self.assertEqual((data["kind"], data["to"], data["write"]), (kind, to, False), path)
        self.run_tool("unarchive", "brain-acme/projects/clients/archive/solo", "--write")
        self.assertEqual(self.read("brain-acme/projects/clients/solo/solo.md"), "# Client: Solo\n\n[globex](../globex/globex.md)\n")

    def test_the_earlier_places_still_count_as_archived_and_archive_files_them_in_the_new_ones(self) -> None:
        self.make_links()
        globex = self.GLOBEX
        self.assertIn("is archived", self.run_tool("brief", "globex/early", code=1).stderr)
        self.assertIn("is archived", self.run_tool("brief", "legacy-tool", code=1).stderr)
        data = self.run_json("archive", "globex/early", "--write")
        self.assertEqual((data["kind"], data["from"], data["to"], data["removed_dirs"], data["link_check"]["exit"]),
                         ("mission", f"{globex}/archive/early", f"{globex}/missions/archive/early", [f"{globex}/archive"], 0))
        self.assertFalse((self.work / f"{globex}/archive").exists())  # the earlier folder, left empty, is removed
        self.assertEqual(self.read(f"{globex}/missions/archive/early/early.md"), "# early\n\n[client](../../../globex.md) [live](../../live/live.md)\n")
        data = self.run_json("archive", "legacy-tool", "--write")
        self.assertEqual((data["kind"], data["from"], data["to"], data["link_check"]["exit"]),
                         ("internal", "brain-acme/projects/archive/legacy-tool", "brain-acme/projects/internal/archive/legacy-tool", 0))
        self.assertEqual(self.read("brain-acme/projects/internal/archive/legacy-tool/legacy-tool.md"), "# legacy-tool\n\n[setup](../../setup/setup.md)\n")

    def test_unarchive_of_an_earlier_place_brings_the_project_back_live(self) -> None:
        self.make_links()
        globex = self.GLOBEX
        data = self.run_json("unarchive", "globex/early", "--write")
        self.assertEqual((data["kind"], data["from"], data["to"], data["link_check"]["exit"]),
                         ("mission", f"{globex}/archive/early", f"{globex}/missions/early", 0))
        self.assertEqual(self.read(f"{globex}/missions/early/early.md"), "# early\n\n[client](../../globex.md) [live](../live/live.md)\n")
        data = self.run_json("unarchive", "legacy-tool", "--write")
        self.assertEqual((data["kind"], data["to"], data["link_check"]["exit"]), ("internal", "brain-acme/projects/internal/legacy-tool", 0))
        self.run_tool("brief", "globex/early")  # live now

    def test_unarchive_refuses_a_mission_that_sits_in_an_archived_client(self) -> None:
        self.make_links()
        self.run_tool("archive", "clients/umbrella", "--write")
        before = self.snapshot()
        archived = "brain-acme/projects/clients/archive/umbrella"
        for wanted in (f"{archived}/missions/alpha", "umbrella/alpha"):
            for flags in ((), ("--write",)):
                error = self.run_tool("unarchive", wanted, *flags, code=1).stderr
                shelf = archived.removeprefix("brain-acme/")  # the message names the folders from the brain
                self.assertIn(f"sits in {shelf}, which is archived: unarchive {shelf} first", error)
        self.assertEqual(self.snapshot(), before)
        # a mission archived on its own inside the archived client reads the same way
        self.assertIn("is archived", self.run_tool("brief", "umbrella/alpha", code=1).stderr)
        self.assertIn(f"unarchive {archived} --write", self.run_tool("changes", "--since", "30d", "--project", "umbrella/beta", code=1).stderr)

    def test_the_client_is_not_archived_again_once_it_is_archived(self) -> None:
        self.make_links()
        self.run_tool("archive", "clients/umbrella", "--write")
        before = self.snapshot()
        error = self.run_tool("archive", "clients/umbrella", code=1).stderr
        self.assertIn("no client umbrella (an archived client is unarchived)", error)
        self.assertIn("already archived", self.run_tool("archive", "brain-acme/projects/clients/archive/umbrella", code=1).stderr)
        self.assertIn("already archived", self.run_tool("archive", "umbrella/alpha", code=1).stderr)
        self.assertEqual(self.snapshot(), before)

    def test_refusals_leave_the_tree_unchanged(self) -> None:
        self.make_links()
        (self.work / f"{self.GLOBEX}/missions/archive/old").mkdir()  # the place archive would move to is taken
        self.write(f"{self.GLOBEX}/missions/archive/old/taken.md", "# taken\n")
        self.write(f"{self.GLOBEX}/missions/live/state/actions.md",  # unfinished work
                   "# Actions — live\n\n## Open\n- [ ] **LIV-002** — Jane Doe — Still to do\n- [w] **LIV-003** — Jane Doe — Waiting\n\n## Done\n")
        self.write("brain-acme/projects/clients/globex/workspace/workspace.md", "# workspace\n")
        self.project(f"{self.GLOBEX}/workspace", actions=(("WRK", "x", ""),))  # not clients/<c>/missions/<m>
        self.project("brain-acme/projects/clients/archive/umbrella/missions/alpha", actions=(("UMB", "x", ""),))  # clients/archive/umbrella taken
        before = self.snapshot()

        def refused(*args: str, error: str) -> None:
            result = self.run_tool(*args, code=1)
            self.assertIn(error, result.stderr + result.stdout)
            self.assertEqual(self.snapshot(), before)

        for flags in ((), ("--write",)):
            refused("archive", "globex/live", *flags, error="cannot archive globex / live (brain-acme): 2 action(s) still to do, in progress or waiting:")
            refused("archive", "globex/old", *flags, error=f"cannot archive globex / old: {self.GLOBEX}/missions/archive/old already exists")
            refused("archive", "clients/umbrella", *flags, error="cannot archive client umbrella: brain-acme/projects/clients/archive/umbrella already exists")
            refused("archive", "setup", *flags, error="setup is the brain's own project (actions without a mission, prefix SET): it is never archived")
            refused("archive", "brain-acme/projects/internal/setup", *flags, error="it is never archived")
            refused("archive", "old-tool", *flags, error="already archived")
            refused("archive", "globex/legacy", *flags, error="already archived")
            refused("archive", f"{self.GLOBEX}/missions/archive/legacy", *flags, error="already archived")
            refused("unarchive", "globex/live", *flags, error="is not archived")
            refused("unarchive", "clients/globex", *flags, error="no archived client globex")
            refused("archive", "workspace", *flags, error="is not a client mission (projects/clients/<client>/missions/<mission>/), "
                                                          "an internal project (projects/internal/<project>/) or a client (projects/clients/<client>/): nothing to archive")
        listing = self.run_tool("archive", "globex/live", code=1).stderr
        self.assertIn("  LIV-002 [ ] Still to do\n  LIV-003 [w] Waiting\n", listing)
        self.assertIn("Close or cancel them first (uv run tools/brain/action.py update ID --state done|cancelled), then archive again.", listing)
        # --json names the open actions
        data = self.run_json("archive", "globex/live", code=1)
        self.assertEqual((data["refused"], data["kind"], [(item["id"], item["state"], item["title"]) for item in data["open_actions"]]),
                         ("open actions", "mission", [("LIV-002", " ", "Still to do"), ("LIV-003", "w", "Waiting")]))
        self.assertEqual(self.snapshot(), before)

    def test_a_client_with_an_open_action_in_any_mission_is_refused_and_the_actions_are_listed_with_their_project(self) -> None:
        self.make_links()
        before = self.snapshot()
        for flags in ((), ("--write",)):
            for client in ("clients/initech", "brain-acme/projects/clients/initech", "clients/globex"):
                error = self.run_tool("archive", client, *flags, code=1).stderr
                self.assertIn("action(s) still to do, in progress or waiting:", error)
        error = self.run_tool("archive", "clients/initech", code=1).stderr
        self.assertIn("cannot archive client initech (brain-acme): 1 action(s) still to do, in progress or waiting:", error)
        self.assertIn("  INI-001 [ ] Task 1  (initech / rollout)\n", error)  # the project label, as the mission is not named otherwise
        self.assertNotIn("(initech / pilot)", error)  # a closed mission lists nothing
        data = self.run_json("archive", "clients/initech", code=1)
        self.assertEqual((data["refused"], data["kind"], data["project"]), ("open actions", "client", "client initech"))
        self.assertEqual([(item["id"], item["state"], item["project"]) for item in data["open_actions"]], [("INI-001", " ", "initech / rollout")])
        self.assertIn("projects/clients/initech/missions/rollout/state/actions.md", data["open_actions"][0]["register"])
        waiting = self.run_json("archive", "clients/globex", code=1)  # migration (open, in progress, waiting), in a client with other finished missions
        self.assertEqual({item["project"] for item in waiting["open_actions"]}, {"globex / migration"})
        self.assertEqual({item["state"] for item in waiting["open_actions"]}, {" ", "/", "w"})
        self.assertEqual(self.snapshot(), before)
        # a finished mission of the client does not stop the others from being archived one by one, but the client stays
        self.run_tool("archive", "initech/pilot", "--write")
        self.assertIn("1 action(s)", self.run_tool("archive", "clients/initech", code=1).stderr)

    def test_unarchive_refuses_a_target_that_exists_and_an_unknown_layout(self) -> None:
        self.make_links()
        (self.work / "brain-acme/projects/internal/old-tool").mkdir()
        self.write("brain-acme/projects/internal/old-tool/x.md", "# x\n")
        before = self.snapshot()
        error = self.run_tool("unarchive", "old-tool", code=1).stderr
        self.assertIn("cannot unarchive old-tool: brain-acme/projects/internal/old-tool already exists", error)
        self.assertEqual(self.snapshot(), before)

    def test_the_archive_commands_use_the_brain_option(self) -> None:
        self.make_links()
        self.project("brain-abacus/projects/internal/done", actions=(("DON", "x", ""),))
        data = self.run_json("archive", "done", "--brain", "brain-abacus", "--write")
        self.assertEqual((data["brain"], data["to"], data["created_dirs"]),
                         ("brain-abacus", "brain-abacus/projects/internal/archive/done", ["brain-abacus/projects/internal/archive"]))
        self.run_tool("archive", "done", "--brain", "brain-acme", code=1)


if __name__ == "__main__":
    unittest.main()
