"""Regression checks for migrate-english.py: French format labels to English, content untouched (temporary brain)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/brain/migrate-english.py"
ACTION = ROOT / "tools/brain/action.py"
DECISION = ROOT / "tools/brain/decision.py"

ACTIONS = """# Actions — Mission

> Registre de test : la citation reste telle quelle, même avec ## Ouvertes ou créée : dedans.

## Ouvertes
- [ ] **ACM-001** — Jane — Préparer l'atelier #lot/ateliers ➕ 2026-10-01 📅 2026-10-20
    - échéance: avant le comité
    - source: [CR](../sources/2026-10/2026-10-01-cr-kickoff.md)
    - créée : 2026-10-01 09:00
    - mise à jour : 2026-10-02 10:00
    - 02/10 : relancée, la réponse « créée : » arrive
    - 03/10 (CR) : point fait
    - limite: fin octobre
- [w] **ACM-002** — Jane — Attendre le retour
    - échéance : semaine prochaine
    - source : mail du 01/10

## Terminées
- [x] **ACM-003** — Jane — Livrer ✅ 2026-10-05
    - source: s
    - faite : livré le 05/10
- [x] **ACM-004** — Jane — Relire ✅ 2026-10-06
    - source: s
    - faite: relu
    - fait le 06/10 : vu en réunion
- [x] **ACM-005** — Jane — Envoyer ✅ 2026-10-06
    - source: s
    - fait : envoyé

## Annulées
- [-] **ACM-006** — Jane — Abandonner ❌ 2026-10-07
    - annulée le 2026-10-07 par Jane — [source](../sources/2026-10/2026-10-01-cr-kickoff.md)
"""

DECISIONS = """# Décisions — Mission

> Garder la source et le statut de chaque décision.

## Proposées

### Choisir l'outil (2026-10-01, statut : proposée)
- **Contexte :** besoin d'un outil.
- **Décision :** prendre l'outil A.
- **Conséquences :** migration.
- **Source :** [CR](../sources/2026-10/2026-10-01-cr-kickoff.md)

## Validées

### Ancienne règle (2026-09-01, statut : active)
- **Décision :** garder B.
- **Source et validation :** Jane, 2026-09-01.

### Règle datée (2026-09-02)
- **Décision :** C.
- **Validation :** Jane, 2026-09-02.
- **Suite :** voir plus tard.

## Refusées / remplacées

### Vieille règle (2026-08-01, statut : remplacée)
- **Décision :** D.
- **Remplacée par :** « Ancienne règle » (2026-09-01).
"""

BULLET_DECISIONS = """# Décisions — Interne

## Proposées
- Passer à l'outil B — proposée par Jane — source : [CR](../sources/x.md)

## Validées

## Refusées / remplacées
"""

PAGE = """# Mission: Mission

## Timeline
Mois précédents : [2026-09](journal/2026-09.md)
- 2026-10-01 — lancement (modèle)
"""

PERSON = """---
nom: Jane Doe
organisation: Acme
missions: [mission]
alias: [Jane]
role: Cheffe de projet
email:
derniere_maj: 2026-10-01
---

# Jane Doe

nom : ce texte du corps ne change pas.
"""

TASKS = """# Actions

> [Pilotage](#pilotage) · [Liste par projet](#liste-par-projet) · [Kanban](#kanban) · [Historique](#historique) · [Inbox](inbox.md)

```meta-bind-button
label: Nouvelle action
actions:
  - type: runTemplaterFile
    templateFile: kit/brain/templates/templater/nouvelle-action.md
```

## Pilotage

> [!task-focus]+ Aujourd'hui
> ```tasks
> path regex matches /^brain\\/projects\\/.*\\/state\\/actions\\.md$/
> (status.type is TODO) OR (status.type is IN_PROGRESS)
> status.name does not include attente
> description regex matches /\\*\\* — [^—]*\\bJane\\b/
> ```

> [!task-wait]+ À relancer
> ```tasks
> status.name includes attente
> ```

> [!task-project]- [Mission](projects/clients/acme/missions/mission/mission.md)
> ```tasks
> path includes brain/projects/clients/acme/missions/mission/state/actions.md
> (status.type is TODO) OR (status.type is IN_PROGRESS)
> ```

> [!task-project]- Mes actions
> ```tasks
> (status.type is IN_PROGRESS) OR (status.name includes attente) OR ((status.type is TODO) AND (status.name does not include attente) AND (description regex matches /x/))
> ```

Une phrase écrite à la main reste en français.
"""

SOURCE = "# CR\n\n## Ouvertes\n    - créée : 2026-10-01 09:00\nMois précédents : rien\n"


class MigrateEnglishTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        (self.work / "kit/brain").mkdir(parents=True)
        (self.work / "kit/brain/AGENTS.md").write_text("# AGENTS\n\n## Where information goes\n\n## Several brains\n", encoding="utf-8")
        self.brain = self.work / "brain"
        self.mission = self.brain / "projects/clients/acme/missions/mission"
        files = {
            "AGENTS.md": "# AGENTS.md — brain\n\n## Périmètre\n",
            "inbox/README.md": "Voir [la carte](../AGENTS.md#ranger-linformation).\n",
            "README.md": "Conventions : [plusieurs brains](../kit/brain/AGENTS.md#plusieurs-brains).\n",
            "tasks.md": TASKS,
            "people/jane-doe.md": PERSON,
            "people/john.md": "# John\n\n- **Role:** test\n",
            "people/README.md": "nom: pas une fiche\n",
            "projects/clients/acme/acme.md": "# Client: Acme\n",
            "projects/clients/acme/missions/mission/mission.md": PAGE,
            "projects/clients/acme/missions/mission/state/actions.md": ACTIONS,
            "projects/clients/acme/missions/mission/state/decisions.md": DECISIONS,
            "projects/clients/acme/missions/mission/sources/2026-10/2026-10-01-cr-kickoff.md": SOURCE,
            "projects/clients/acme/missions/mission/journal/2026-09.md": "# Journal\n\nMois précédents : rien\n",
            "projects/clients/acme/missions/mission/notes/2026-10-01-idee.md": "    - créée : 2026-10-01 09:00\n",
            "projects/internal/interne/interne.md": "# Project: Interne\n",
            "projects/internal/interne/state/actions.md": "# Actions — Interne\n\n## Ouvertes\n\n## Terminées\n\n## Annulées\n",
            "projects/internal/interne/state/decisions.md": BULLET_DECISIONS,
            ".data/transcripts.json": json.dumps({"a.txt": {"status": "traite", "date_traitement": "2026-10-01", "destinations": ["x"], "note": "traite"},
                                                  "b.txt": {"status": "a-decider"}}, ensure_ascii=False, indent=2) + "\n",
            ".data/messages-state.json": '{\n  "mail_processed_ids": [{"id": "1", "status": "traite"}, {"id": "2", "status": "ignore"}]\n}\n',
            ".data/brain.json": '{\n  "scope": "employeur",\n  "description": "perso"\n}\n',
        }
        for name, text in files.items():
            path = self.brain / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.before = {path: path.read_bytes() for path in self.brain.rglob("*") if path.is_file()}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_tool(self, tool: Path, *args: str, code: int = 0) -> str:
        env = {**os.environ, "WORK_DIR": str(self.work), "BRAIN_DIR": str(self.brain), "ACTION_NOW": "2026-10-13 14:32"}
        result = subprocess.run([sys.executable, str(tool), *args], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def read(self, name: str) -> str:
        return (self.brain / name).read_text(encoding="utf-8")

    def test_dry_run_reports_and_writes_nothing(self) -> None:
        out = self.run_tool(TOOL, "--diff")
        self.assertIn("projects/clients/acme/missions/mission/state/actions.md:", out)
        self.assertIn("to convert", out)
        self.assertIn("+## Open", out)
        self.assertEqual({path: path.read_bytes() for path in self.brain.rglob("*") if path.is_file()}, self.before)
        self.run_tool(TOOL, "--check", code=1)

    def test_write_converts_only_the_labels(self) -> None:
        out = self.run_tool(TOOL, "--write", "--allow-dirty")
        actions = self.read("projects/clients/acme/missions/mission/state/actions.md")
        expected = (ACTIONS
                    .replace("## Ouvertes\n- [ ]", "## Open\n- [ ]").replace("## Terminées\n- [x]", "## Done\n- [x]")
                    .replace("## Annulées\n- [-]", "## Cancelled\n- [-]")
                    .replace("#lot/ateliers", "#group/ateliers")
                    .replace("    - échéance: avant", "    - due: avant").replace("    - échéance : semaine", "    - due: semaine")
                    .replace("    - créée : 2026-10-01", "    - created: 2026-10-01").replace("    - mise à jour : ", "    - updated: ")
                    .replace("    - 02/10 : relancée", "    - 02/10: relancée").replace("    - source : mail", "    - source: mail")
                    .replace("    - faite : livré", "    - done: livré").replace("    - faite: relu", "    - done: relu")
                    .replace("    - fait : envoyé", "    - done: envoyé")
                    .replace("    - annulée le 2026-10-07 par Jane", "    - cancelled: 2026-10-07 by Jane"))
        self.assertEqual(actions, expected)
        decisions = self.read("projects/clients/acme/missions/mission/state/decisions.md")
        for line in ("# Decisions — Mission", "## Proposed", "## Accepted", "## Rejected / superseded",
                     "### Choisir l'outil (2026-10-01, status: proposed)", "- **Context:** besoin d'un outil.",
                     "- **Decision:** prendre l'outil A.", "- **Consequences:** migration.", "### Ancienne règle (2026-09-01, status: active)",
                     "### Règle datée (2026-09-02)", "- **Accepted:** Jane, 2026-09-02.", "### Vieille règle (2026-08-01, status: superseded)",
                     "- **Superseded by:** « Ancienne règle » (2026-09-01).", "- **Source and acceptance:** Jane, 2026-09-01.",
                     "- **Follow-up:** voir plus tard.", "> Keep the source and the status of each decision."):
            self.assertIn(line + "\n", decisions)
        self.assertIn("Previous months: [2026-09](journal/2026-09.md)\n", self.read("projects/clients/acme/missions/mission/mission.md"))
        person = self.read("people/jane-doe.md")
        self.assertTrue(person.startswith("---\nname: Jane Doe\norganization: Acme\nmissions: [mission]\naliases: [Jane]\nrole: Cheffe de projet\n"
                                          "email:\nupdated: 2026-10-01\n---\n"), person)
        self.assertIn("\nnom : ce texte du corps ne change pas.\n", person)
        tasks = self.read("tasks.md")
        for line in ("> [Focus](#focus) · [By project](#by-project) · [Kanban](#kanban) · [History](#history) · [Inbox](inbox.md)",
                     "label: New action", "    templateFile: kit/brain/templates/templater/new-action.md", "## Focus",
                     "> [!task-focus]+ Today", "> [!task-wait]+ Follow up", "> status.type is ON_HOLD",
                     "> (status.type is TODO) OR (status.type is IN_PROGRESS) OR (status.type is ON_HOLD)",
                     "> description regex matches /\\*\\* — [^—]*\\bJane\\b/", "> (status.type is IN_PROGRESS) OR (status.type is ON_HOLD) OR ((status.type is TODO) AND (status.type is not ON_HOLD) AND (description regex matches /x/))",
                     "Une phrase écrite à la main reste en français."):
            self.assertIn(line + "\n", tasks)
        self.assertNotIn("attente", tasks)
        focus = tasks.split("[!task-focus]")[1].split("[!task-wait]")[0]
        self.assertIn("> (status.type is TODO) OR (status.type is IN_PROGRESS)\n", focus)  # waiting stays out of Today
        self.assertNotIn("ON_HOLD", focus)
        self.assertEqual(self.read("inbox/README.md"), "Voir [la carte](../../kit/brain/AGENTS.md#where-information-goes).\n")
        self.assertIn("(../kit/brain/AGENTS.md#several-brains)", self.read("README.md"))
        transcripts = json.loads(self.read(".data/transcripts.json"))
        self.assertEqual(transcripts["a.txt"], {"status": "processed", "processed_on": "2026-10-01", "destinations": ["x"], "note": "traite"})
        self.assertEqual(transcripts["b.txt"], {"status": "undecided"})
        self.assertEqual(self.read(".data/messages-state.json"),
                         '{\n  "mail_processed_ids": [{"id": "1", "status": "processed"}, {"id": "2", "status": "ignored"}]\n}\n')
        self.assertEqual(json.loads(self.read(".data/brain.json")), {"scope": "employer", "description": "perso"})
        for name in ("projects/clients/acme/missions/mission/sources/2026-10/2026-10-01-cr-kickoff.md",
                     "projects/clients/acme/missions/mission/journal/2026-09.md",
                     "projects/clients/acme/missions/mission/notes/2026-10-01-idee.md", "people/john.md", "people/README.md", "AGENTS.md"):
            self.assertEqual((self.brain / name).read_bytes(), self.before[self.brain / name], name)
        for left in ("« fait le DD/MM » kept as written", "« limite: » kept as written", "history line with a qualifier",
                     "status « active » kept", "decision written as a bullet", "people/john.md: left as is — no front matter"):
            self.assertIn(left, out)
        self.assertNotIn("field « Suite » kept", out)

    def test_second_run_finds_nothing_and_tools_read_the_result(self) -> None:
        self.run_tool(TOOL, "--write", "--allow-dirty")
        self.assertIn("Total: 0 change(s) to convert in 0 file(s)", self.run_tool(TOOL))
        self.run_tool(TOOL, "--check")
        checked = self.run_tool(ACTION, "check")
        self.assertNotIn("French labels", checked)
        listed = json.loads(self.run_tool(DECISION, "list", "--project", "acme/mission"))
        self.assertEqual([d["state"] for d in listed], ["proposed", "accepted", "accepted", "rejected"])
        shown = json.loads(self.run_tool(ACTION, "show", "ACM-001"))
        self.assertEqual((shown["group"], shown["created_at"], shown["updated_at"]), ("ateliers", "2026-10-01 09:00", "2026-10-02 10:00"))

    def test_write_refuses_files_with_uncommitted_changes(self) -> None:
        git = ["git", "-C", str(self.brain), "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "chore: init", "--no-verify"], check=True)
        register = self.brain / "projects/internal/interne/state/actions.md"
        register.write_text(register.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        out = self.run_tool(TOOL, "--write", code=1)
        self.assertIn("projects/internal/interne/state/actions.md: 3 change(s), refused (uncommitted changes)", out)
        self.assertIn("## Ouvertes", register.read_text(encoding="utf-8"))
        self.assertIn("## Open", self.read("projects/clients/acme/missions/mission/state/actions.md"))

    def test_default_brain_is_found_under_another_name_without_brain_dir(self) -> None:
        self.brain.rename(self.work / "brain-initech")  # the only brain of the Work root
        env = {key: value for key, value in os.environ.items() if key != "BRAIN_DIR"}
        result = subprocess.run([sys.executable, str(TOOL), "--check"], env={**env, "WORK_DIR": str(self.work)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("projects/clients/acme/missions/mission/state/actions.md:", result.stdout)

    def test_seed_tasks_page_is_already_english(self) -> None:
        seed = (ROOT / "kit/brain/seed/tasks.md").read_text(encoding="utf-8")
        self.assertNotIn("attente", seed)
        self.assertIn("templater/new-action.md", seed)
        (self.brain / "tasks.md").write_text(seed.replace("{{BRAIN}}", "brain"), encoding="utf-8")
        self.assertNotIn("tasks.md:", self.run_tool(TOOL))


MISSION_PAGE = """# Mission: Portail

> Index court de la mission ; les registres et sources font foi pour le détail.

- **Client :** [Acme](../../acme.md)
- **Statut :** actif
- **Objectif :** livrer le portail.
- **Boond :** `123-Acme`
- **Tableau :** [tasks](../../../../../tasks.md)

## En bref
- Le statut est actif ; lire selon le besoin, puis En bref.

## État actuel

> État au 2026-10-02 (Model).

- Avancement normal.

## Architecture cible
- **Statut :** en revue, ce libellé du corps reste tel quel.

## Lire selon le besoin
- [Actions](state/actions.md)

## Timeline
Mois précédents : [2026-09](journal/2026-09.md)
- 2026-10-01 — État actuel : Mois précédents et Retour au projet restent en prose (Model)
"""

CLIENT_PAGE = """# Client: Acme

> Index durable du client. L'état et les sources sont dans la mission.

- **Interlocuteurs :** [Jane Doe](../../../people/jane-doe.md)

## En bref
- Client de test.

## Conventions client
- Écrire en français.
"""

MINUTES_A = """---
date: 2026-10-01
heure: "09:00"
type: cr
client: acme
mission: portail
titre: Kick-off
participants: [Jane Doe]
fiabilite: moyenne
redige_par: "cr-reunion (Model)"
---

# 2026-10-01 — Kick-off

> CR rédigé à partir du transcript. Fiche : [portail](../../portail.md).

Fiche : [portail](../../portail.md).

## En bref
- Jane présente le plan ; le Résumé et les Sujets sont prêts.

## Participants
- Jane Doe — Acme

## Sujets

### Retenu
- Le point « Points à vérifier » reste en prose.

## Décisions proposées
- **Proposée** — Choisir l'outil A — Jane.
- **À confirmer** — Garder B — Jane.

## Actions
- **Nouvelle · ACM-001** — Jane — Préparer l'atelier — 20/10.
- **Suivi · ACM-002 et ACM-003** — échéance décalée.
- **Suivi :** ce sujet garde son libellé.

## Points à vérifier
- Le nom exact du client.

## Ce qui a changé depuis le dernier point
_Vient de la mémoire._
- ACM-002 avance.

## Changements depuis la restitution
- Rien.

## Addendum du 05/10
- Précision.

```markdown
## Résumé
```
"""

MINUTES_A_EXPECTED = """---
date: 2026-10-01
time: "09:00"
type: cr
client: acme
mission: portail
title: Kick-off
participants: [Jane Doe]
reliability: medium
written_by: "cr-reunion (Model)"
---

# 2026-10-01 — Kick-off

> CR rédigé à partir du transcript. Fiche : [portail](../../portail.md).

Mission page: [portail](../../portail.md).

## Summary
- Jane présente le plan ; le Résumé et les Sujets sont prêts.

## Participants
- Jane Doe — Acme

## Key points

### Retenu
- Le point « Points à vérifier » reste en prose.

## Decisions
- **To confirm** — Choisir l'outil A — Jane.
- **To confirm** — Garder B — Jane.

## Actions and follow-up
- **New · ACM-001** — Jane — Préparer l'atelier — 20/10.
- **Follow-up · ACM-002 and ACM-003** — échéance décalée.
- **Suivi :** ce sujet garde son libellé.

## To check
- Le nom exact du client.

## Changes since the last meeting
_From memory._
- ACM-002 avance.

## Changements depuis la restitution
- Rien.

## Addendum — 05/10
- Précision.

```markdown
## Résumé
```
"""

MINUTES_B = """---
date: 2026-10-03
type: cr
projet: interne
titre: Point
title: Point
---

# 2026-10-03 — Point

Fiche : [interne](../../interne.md).

## Summary
Déjà en anglais.

## Résumé
Ancienne section gardée.

## Retenu
- **Budget :** validé.

## Actions et suivi
- **Nouvelle** — Jane — Envoyer le devis.

## À vérifier
- Le montant.

## Détail
Rien.
"""

PERSON_PAGE = """---
name: Jane Doe
organization: Acme
missions: [portail]
aliases: []
role: Cheffe de projet
email:
updated: 2026-10-01
---

# Jane Doe

- **Projets :** [portail](../projects/clients/acme/missions/portail/portail.md)

## Rôle et périmètre
- Cheffe de projet ; son rôle et périmètre restent en prose.

## Ce qu'il/elle attend
- Des points courts.

## Historique des échanges
- 2026-10-01 — kick-off.

## Mentoring / progression
- **Focus actuel :** cadrage.
- **Forces :** synthèse.
"""


class StructureTest(unittest.TestCase):
    """Headings, front matter, header labels, tags and boilerplate lines; content and topic headings untouched."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        (self.work / "kit/brain").mkdir(parents=True)
        self.brain = self.work / "brain"
        mission = "projects/clients/acme/missions/portail"
        files = {
            "projects/clients/acme/acme.md": CLIENT_PAGE,
            f"{mission}/portail.md": MISSION_PAGE,
            f"{mission}/state/actions.md": "# Actions — Portail\n\n> Ce registre fait foi pour ID, responsable, échéance et statut. "
                                          "Le tableau [`tasks.md`](../../../../../tasks.md) l'affiche avec le plugin Tasks.\n\n## Open\n",
            f"{mission}/state/decisions.md": "# Decisions — Portail\n\n> Garder la source et le statut de chaque décision.\n\n## Proposed\n",
            f"{mission}/state/glossary.md": "# Glossaire — Portail\n\n> Termes, acronymes et erreurs de transcription fréquentes "
                                           "(entre parenthèses) — sert à reconnaître la mission dans un CR ou un mail.\n\n- **SSO :** connexion unique.\n",
            f"{mission}/sources/2026-10/2026-10-01-cr-kickoff.md": MINUTES_A,
            f"{mission}/sources/2026-10/index.md": "# Sources — 2026-10 — portail\n\n[Retour à la mission](../../portail.md)\n\n"
                                                   "- 2026-10-01 · cr · [Kick-off](2026-10-01-cr-kickoff.md) — Retour à la mission prévu.\n"
                                                   "- 2026-10-02 · analyse locale · [Analyse](2026-10-02-analyse-depot.md) — dépôt lu.\n",
            f"{mission}/journal/2026-09.md": "# Journal — Portail — 2026-09\n\n[Retour au projet](../portail.md)\n\n"
                                            "> Archive du journal de la mission Portail pour septembre 2026 : entrées déplacées depuis la fiche "
                                            "le 2026-10-12. Les mois en cours restent dans la fiche.\n\n- 2026-09-30 — Mois précédents : prose.\n",
            f"{mission}/notes/2026-10-01-idee.md": "# Idée\n\n> Note du 01/10/2026 · projet : [portail](../portail.md)\n\n## Liens\n- Texte.\n",
            f"{mission}/workstreams/architecture.md": "# Architecture\n\n## En bref\n- Un workstream garde ses titres.\n",
            "projects/internal/interne/interne.md": "# Project: Interne\n\n- **Status:** active\n",
            "projects/internal/interne/state/actions.md": "# Actions — Interne\n\n> Ce registre fait foi pour ID, responsable, échéance et statut ; "
                                                          "conserver le préfixe d'ID du client, y compris entre missions (préfixe GLX, validé par Jane le "
                                                          "2026-10-01).\n\n## Open\n",
            "projects/internal/interne/sources/2026-10/2026-10-03-cr-point.md": MINUTES_B,
            "projects/internal/setup/setup.md": "# Setup du système\n\n> Projet interne dédié à l'installation, aux conventions, aux automatisations "
                                                "et à la maintenance de l'espace de travail.\n\n## État\n\n- **Statut :** actif\n"
                                                "- **Objectif :** garder le brain cohérent.\n\n## Liens\n\n- [Actions](state/actions.md)\n\n## Timeline\n",
            "projects/internal/setup/state/actions.md": "# Actions — Setup du système\n\n> Registre faisant foi pour les actions de maintenance "
                                                        "du brain. Préfixe réservé : `SET`.\n\n## Open\n",
            "people/jane-doe.md": PERSON_PAGE,
            "inbox/inbox.md": "# 📥 Inbox — Scratchpad\n\n> - tasks.md = le tableau qui les affiche (plugin Tasks)\n\n- une capture : le tableau qui les affiche\n",
        }
        for name, text in files.items():
            path = self.brain / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.mission = mission
        self.before = self.snapshot()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def snapshot(self) -> dict[Path, bytes]:
        return {path: path.read_bytes() for path in self.brain.rglob("*") if path.is_file()}

    def run_tool(self, *args: str, code: int = 0) -> str:
        env = {**os.environ, "WORK_DIR": str(self.work), "BRAIN_DIR": str(self.brain)}
        result = subprocess.run([sys.executable, str(TOOL), *args], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def read(self, name: str) -> str:
        return (self.brain / name).read_text(encoding="utf-8")

    def test_dry_run_summarizes_per_file_and_writes_nothing(self) -> None:
        out = self.run_tool()
        self.assertIn(f"{self.mission}/sources/2026-10/2026-10-01-cr-kickoff.md: ", out)
        self.assertIn("to convert — ", out)
        for rule in ("heading", "front matter", "tag", "header label", "boilerplate", "back link", "person label"):
            self.assertIn(f"{rule} ", out.split("By rule: ")[1])
        self.assertEqual(self.snapshot(), self.before)
        self.run_tool("--check", code=1)
        self.assertEqual(self.snapshot(), self.before)

    def test_write_renames_structure_and_keeps_content(self) -> None:
        out = self.run_tool("--write", "--allow-dirty")
        self.assertEqual(self.read(f"{self.mission}/sources/2026-10/2026-10-01-cr-kickoff.md"), MINUTES_A_EXPECTED)
        page = self.read(f"{self.mission}/portail.md")
        self.assertEqual(page, MISSION_PAGE
                         .replace("> Index court de la mission ; les registres et sources font foi pour le détail.",
                                  "> Short index of the mission; the registers and sources are authoritative for the detail.")
                         .replace("- **Client :**", "- **Client:**").replace("- **Statut :** actif", "- **Status:** active")
                         .replace("- **Objectif :**", "- **Goal:**").replace("- **Boond :**", "- **Boond:**")
                         .replace("- **Tableau :**", "- **Board:**").replace("## En bref", "## Summary")
                         .replace("## État actuel", "## Current state").replace("> État au 2026-10-02 (Model).", "> As of 2026-10-02 (Model).")
                         .replace("## Lire selon le besoin", "## Read as needed").replace("Mois précédents : [", "Previous months: ["))
        self.assertIn("## Architecture cible\n- **Statut :** en revue, ce libellé du corps reste tel quel.\n", page)  # topic heading, body label
        self.assertIn("- Le statut est actif ; lire selon le besoin, puis En bref.\n", page)  # prose with structural words
        self.assertEqual(self.read("projects/clients/acme/acme.md"), CLIENT_PAGE
                         .replace("> Index durable du client. L'état et les sources sont dans la mission.",
                                  "> Durable index of the client. The state and the sources are in the mission.")
                         .replace("**Interlocuteurs :**", "**Contacts:**").replace("## En bref", "## Summary")
                         .replace("## Conventions client", "## Client conventions"))
        minutes = self.read("projects/internal/interne/sources/2026-10/2026-10-03-cr-point.md")
        for line in ("project: interne", "titre: Point", "title: Point", "Project page: [interne](../../interne.md).", "## Summary",
                     "## Résumé", "## Key points", "- **Budget :** validé.", "## Actions and follow-up", "- **New** — Jane — Envoyer le devis.",
                     "## To check", "## Details"):
            self.assertIn(line + "\n", minutes)
        person = self.read("people/jane-doe.md")
        self.assertEqual(person, PERSON_PAGE.replace("**Projets :**", "**Projects:**").replace("## Rôle et périmètre", "## Role and scope")
                         .replace("## Ce qu'il/elle attend", "## Expectations").replace("## Historique des échanges", "## Interaction log")
                         .replace("**Focus actuel :**", "**Current focus:**").replace("**Forces :**", "**Strengths:**"))
        self.assertEqual(self.read(f"{self.mission}/sources/2026-10/index.md"),
                         "# Sources — 2026-10 — portail\n\n[Back to the mission](../../portail.md)\n\n"
                         "- 2026-10-01 · cr · [Kick-off](2026-10-01-cr-kickoff.md) — Retour à la mission prévu.\n"
                         "- 2026-10-02 · local analysis · [Analyse](2026-10-02-analyse-depot.md) — dépôt lu.\n")
        self.assertEqual(self.read(f"{self.mission}/journal/2026-09.md"),
                         "# Journal — Portail — 2026-09\n\n[Back to project](../portail.md)\n\n> Journal archive of mission Portail for September "
                         "2026: entries moved from the project page on 2026-10-12. The current month stays on the page.\n\n"
                         "- 2026-09-30 — Mois précédents : prose.\n")
        self.assertEqual(self.read(f"{self.mission}/notes/2026-10-01-idee.md"),
                         "# Idée\n\n> Note from 01/10/2026 · project: [portail](../portail.md)\n\n## Liens\n- Texte.\n")
        self.assertIn("> This register is authoritative for ID, owner, due date and status. The board [`tasks.md`](../../../../../tasks.md) "
                      "displays it with the Tasks plugin.\n", self.read(f"{self.mission}/state/actions.md"))
        self.assertIn("> Keep the source and the status of each decision.\n", self.read(f"{self.mission}/state/decisions.md"))
        glossary = self.read(f"{self.mission}/state/glossary.md")
        self.assertTrue(glossary.startswith("# Glossary — Portail\n\n> Terms, acronyms and frequent transcription errors (in parentheses)"))
        self.assertIn("- **SSO :** connexion unique.\n", glossary)
        self.assertEqual(self.read("projects/internal/setup/setup.md"),
                         "# System setup\n\n> Internal project dedicated to the installation, conventions, automations and maintenance of the "
                         "workspace.\n\n## Status\n\n- **Status:** active\n- **Goal:** garder le brain cohérent.\n\n## Read as needed\n\n"
                         "- [Actions](state/actions.md)\n\n## Timeline\n")
        self.assertEqual(self.read("projects/internal/setup/state/actions.md"),
                         "# Actions — System setup\n\n> Authoritative register for the brain's maintenance actions. Reserved prefix: `SET`.\n\n## Open\n")
        self.assertEqual(self.read("inbox/inbox.md"), "# 📥 Inbox — Scratchpad\n\n> - tasks.md = the board that displays them (Tasks plugin)\n\n"
                                                      "- une capture : le tableau qui les affiche\n")
        for name in (f"{self.mission}/workstreams/architecture.md", "projects/internal/interne/state/actions.md", "projects/internal/interne/interne.md"):
            self.assertEqual((self.brain / name).read_bytes(), self.before[self.brain / name], name)
        for left in ("heading « Résumé » kept, « Summary » is already in the file", "« titre » kept, « title » already present",
                     "heading « Changements depuis la restitution » kept", "projects/internal/interne/state/actions.md: left as is — line 3: guidance quote"):
            self.assertIn(left, out)

    def test_second_run_finds_nothing(self) -> None:
        self.run_tool("--write", "--allow-dirty")
        after = self.snapshot()
        out = self.run_tool("--write", "--allow-dirty")
        self.assertIn("Total: 0 change(s) written in 0 file(s)", out)
        self.assertEqual(self.snapshot(), after)
        self.run_tool("--check")

    def test_mapping_marks_each_row(self) -> None:
        rows = [line.split("\t") for line in self.run_tool("--mapping").splitlines()]
        self.assertTrue(rows and all(row[0] in ("exact", "judged") and row[3] == "→" for row in rows))
        self.assertIn(["judged", "minutes heading", "Sujets", "→", "Key points"], rows)
        self.assertIn(["exact", "minutes heading", "Retenu", "→", "Key points"], rows)
        self.assertIn(["exact", "page header label", "Tableau", "→", "Board"], rows)


if __name__ == "__main__":
    unittest.main()
