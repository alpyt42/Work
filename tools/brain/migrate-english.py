#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Convert a brain written with the French format labels to the English ones (dry run by default).

Only structural labels change, never written content: section titles, sub-bullet keys and statuses
of the action and decision registers, the `Previous months:` line of project pages, the front-matter
keys of person pages, the Tasks queries, button and seed labels of `tasks.md`, links to renamed kit
headings, and the French values of `.data/transcripts.json`, `.data/messages-state.json` and
`.data/brain.json`.

The structure pass (STRUCTURE tables below) also renames, line by line and only on an exact match:
the template section headings of client, mission, project and person pages and of dated sources
(including the sections of the earlier French minutes formats), the front-matter keys of dated
sources, the bold header labels of project pages (`**Statut :**` → `**Status:**`), the fixed tags of
minutes (`**Nouvelle · ID**` → `**New · ID**`), and the fixed boilerplate lines (guidance quotes of
registers, pages and glossaries, journal headers, back links, note headers, the seed lines of
`inbox/inbox.md`). Each mapping is marked `exact` (the current template or tool writes that English
for that French) or `judged` (an earlier format mapped by meaning, or a translation without template
counterpart); `--mapping` prints the table. A heading is never merged: a rename that would repeat a
heading already in the file is left and listed. Text of sources, notes, entries, actions, decisions,
glossaries, people, workstreams, handoffs, `me/` and `skills/` is never changed, and topic headings are
never in the tables. The brain's own instruction files (`AGENTS.md`, `README.md`, `docs/`) are
translated by hand, not here. What the script cannot convert safely (free variants, decisions written
as bullets, person pages without front matter, boilerplate mixed with content) is listed, not changed.

    uv run tools/brain/migrate-english.py [--brain PATH] [--diff]   report what would change
    uv run tools/brain/migrate-english.py --write                   apply it
    uv run tools/brain/migrate-english.py --check                   exit 1 when something is left to convert
    uv run tools/brain/migrate-english.py --mapping                 print the structure mapping table

Running it again finds nothing: every rule only matches the French forms. `--write` refuses a file
with uncommitted changes (`--allow-dirty` to override); it never commits. `--no-tasks-labels`
keeps the French titles and help of `tasks.md` (its queries and button are still converted).
`--brain PATH` or BRAIN_DIR selects the brain (default: the default brain of Work, see tools/machine/work_config.py).
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WORK = Path(os.environ.get("WORK_DIR", Path(__file__).resolve().parents[2])).resolve()


def default_brain_dir() -> Path:
    """The default brain of WORK (rule of tools/machine/work_config.py); `WORK/brain` when there is none."""
    spec = importlib.util.spec_from_file_location("work_config", Path(__file__).resolve().parents[1] / "machine/work_config.py")
    assert spec and spec.loader
    work_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(work_config)
    try:
        return work_config.default_brain(WORK) or WORK / "brain"
    except work_config.ConfigError as error:
        raise SystemExit(f"work config error: {error}") from None
    except OSError:
        return WORK / "brain"


BRAIN = Path(os.environ["BRAIN_DIR"] if "BRAIN_DIR" in os.environ else default_brain_dir()).resolve()
NEVER = ("sources", "journal", "notes", "workstreams", "handoffs")  # project folders never written

# --- Action registers ----------------------------------------------------------------------------

ACTION_LINE = re.compile(r"^- \[.\] \*\*[A-Z]{2,5}-\d{3}\*\*")
ACTION_SECTIONS = {"Ouvertes": "Open", "Terminées": "Done", "Annulées": "Cancelled"}
ACTION_RULES = [  # (rule, pattern, replacement) on sub-bullets indented by four spaces
    ("created", re.compile(r"^    - créée\s*:\s*"), "    - created: "),
    ("updated", re.compile(r"^    - mise à jour\s*:\s*"), "    - updated: "),
    ("due", re.compile(r"^    - échéance\s*:\s*"), "    - due: "),
    ("done", re.compile(r"^    - faite?\s*:\s*"), "    - done: "),
    ("cancelled", re.compile(r"^    - annulée le (\d{4}-\d{2}-\d{2}) par "), r"    - cancelled: \1 by "),
    ("cancelled", re.compile(r"^    - annulée le (\d{4}-\d{2}-\d{2})"), r"    - cancelled: \1"),
    ("source", re.compile(r"^    - source\s+:\s*"), "    - source: "),
    ("history", re.compile(r"^    - (\d{2}/\d{2}) : "), r"    - \1: "),
]
ACTION_LEFT = [  # free variants reported, not converted
    (re.compile(r"^    - fait le \d{2}/\d{2}"), "« fait le DD/MM » kept as written"),
    (re.compile(r"^    - limite\s*:"), "« limite: » kept as written"),
    (re.compile(r"^    - \d{2}/\d{2}\b(?! : )[^:\n]*\s:\s"), "history line with a qualifier before « : », kept as written"),
]
ARCHIVE_TITLE = re.compile(r"^# Archive des actions (\d{4}) — (.+)$")
ARCHIVE_QUOTE = re.compile(r"^> Archive des actions closes de (.+) en (\d{4}) ; le registre vivant est \[actions\.md\]\(actions\.md\)\. Les ID restent réservés\.$")

# --- Decision registers --------------------------------------------------------------------------

DECISION_SECTIONS = {"Proposées": "Proposed", "Validées": "Accepted", "Refusées / remplacées": "Rejected / superseded"}
DECISION_STATUS = {"proposée": "proposed", "validée": "accepted", "refusée": "rejected", "remplacée": "superseded"}
DECISION_FIELDS = {"Contexte": "Context", "Décision": "Decision", "Conséquences": "Consequences", "Source": "Source",
                   "Validation": "Accepted", "Refus": "Rejected", "Remplacée par": "Superseded by",
                   # judged: fields of an earlier format, no template counterpart
                   "Suite": "Follow-up", "Source et validation": "Source and acceptance"}
STATUS_TAIL = re.compile(r"(\((?:\d{4}-\d{2}-\d{2}, )?)statut\s*:\s*([^()]*)\)\s*$")
FIELD_LINE = re.compile(r"^- \*\*([^*]+?)\s*:\*\*")

# --- Pages, people, data -------------------------------------------------------------------------

PREVIOUS_MONTHS = re.compile(r"^Mois précédents\s*:\s*")
PERSON_KEYS = {"nom": "name", "organisation": "organization", "alias": "aliases", "derniere_maj": "updated"}
TRANSCRIPT_STATUS = {"traite": "processed", "ignore": "ignored", "decoupe": "split", "doublon": "duplicate", "a-decider": "undecided"}
MESSAGE_STATUS = {"traite": "processed", "ignore": "ignored"}
SCOPES = {"perso": "personal", "employeur": "employer"}

# Links to kit headings renamed in English (`kit/brain/AGENTS.md` and `kit/brain/docs/*.md`).
KIT_ANCHORS = {
    "AGENTS.md": {"sorienter-avant-décrire": "get-oriented-before-writing", "ce-qui-fait-foi": "source-of-truth",
                  "ranger-linformation": "where-information-goes", "plusieurs-brains": "several-brains",
                  "finir-le-travail": "finish-the-work", "références-à-ouvrir-au-bon-moment": "references-to-open-when-needed"},
    "docs/CONVENTIONS.md": {"dossiers-et-navigation": "folders-and-navigation", "sources-état-et-journal": "sources-state-and-journal",
                            "tableau-tasks-et-inbox": "tasks-board-and-inbox", "personnes-notes-et-voix": "people-notes-and-voice",
                            "liens-handoffs-et-archives": "links-handoffs-and-archives",
                            "ingestion-et-confidentialité": "ingestion-and-confidentiality", "forme": "form"},
    "docs/WORKFLOWS.md": {"les-fichiers-centraux": "the-central-files", "rythme--à-la-demande": "rhythm--on-demand",
                          "utiliser-la-liste-et-le-kanban-dans-obsidian": "use-the-list-and-the-kanban-in-obsidian",
                          "où-vivent-les-choses": "where-things-live", "exécuter-du-vrai-travail": "doing-real-work",
                          "gestes-de-maintenance-pour-lagent": "maintenance-gestures-for-the-agent"},
    "docs/GIT.md": {"identités-git-et-clés-ssh": "git-identities-and-ssh-keys", "publication-du-brain": "publishing-the-brain",
                    "repos-partagés-et-clones-client": "shared-repos-and-client-clones"},
}
LINK = re.compile(r"\]\(([^)\s#]*)#([^)\s]+)\)")

# --- tasks.md ------------------------------------------------------------------------------------

OLD_FORM = "kit/brain/templates/templater/nouvelle-action.md"
NEW_FORM = "kit/brain/templates/templater/new-action.md"
TASKS_LINES = {  # seed lines of tasks.md before the English formats → their English version
    "Les prochaines actions, la liste par projet et le kanban, au même endroit. Tant que le propriétaire n'est pas renseigné dans le starter, les vues montrent tous les responsables.":
        "Next actions, the list by project and the kanban, in one place. Until the owner is set in the starter, the views show every owner.",
    "> [Pilotage](#pilotage) · [Liste par projet](#liste-par-projet) · [Kanban](#kanban) · [Historique](#historique) · [Inbox](inbox.md)":
        "> [Focus](#focus) · [By project](#by-project) · [Kanban](#kanban) · [History](#history) · [Inbox](inbox.md)",
    "label: Nouvelle action": "label: New action",
    "tooltip: Ajouter une tâche dans le registre du projet choisi": "tooltip: Add a task to the register of the chosen project",
    "Choisis le projet, puis renseigne l'action. Le formulaire la range au bon endroit avec son ID, sa priorité et son échéance.":
        "Choose the project, then fill in the action. The form files it in the right place with its ID, priority and due date.",
    "> [!info]- Dans le navigateur": "> [!info]- In the browser",
    "> Depuis la racine de l'espace de travail, lance `uv run tools/tasks-web/tasks-web.py`, puis ouvre `http://127.0.0.1:8765/`. Cette [interface locale](../tools/tasks-web/README.md) lit et modifie les mêmes registres.":
        "> From the Work root, run `uv run tools/tasks-web/tasks-web.py`, then open `http://127.0.0.1:8765/`. This [local interface](../tools/tasks-web/README.md) reads and edits the same registers.",
    "## Pilotage": "## Focus",
    "> [!task-focus]+ Aujourd'hui": "> [!task-focus]+ Today",
    "> Choisis jusqu'à trois actions avec le crayon 📝 : **Scheduled / Planifiée = aujourd'hui**. Les échéances du jour, les retards et les actions planifiées non terminées remontent ici.":
        "> Pick up to three actions with the pencil 📝: **Scheduled = today**. Today's due dates, overdue actions and unfinished scheduled actions show up here.",
    "> > [!task-active]+ En cours": "> > [!task-active]+ In progress",
    "> > [!task-next]+ À lancer": "> > [!task-next]+ Up next",
    "> > Les 8 premières par priorité, puis échéance. La liste complète reste dans les projets.":
        "> > The first 8 by priority, then due date. The full list stays in the projects.",
    "> [!task-wait]+ À relancer": "> [!task-wait]+ Follow up",
    "> [!task-calendar]- Échéances · 7 prochains jours": "> [!task-calendar]- Due · next 7 days",
    "## Liste par projet": "## By project",
    "> [!task-project]- [Setup du système](projects/internal/setup/setup.md)": "> [!task-project]- [System setup](projects/internal/setup/setup.md)",
    "> [!task-project]- Autres projets": "> [!task-project]- Other projects",
    "Ajoute un encadré dédié quand un projet doit rester visible, puis exclus son registre d'« Autres projets ».":
        "Add a dedicated box when a project must stay visible, then exclude its register from “Other projects”.",
    "Pour déplacer une action, fais un clic droit sur sa case ou utilise le crayon 📝. Les colonnes lisent directement les registres.":
        "To move an action, right-click its checkbox or use the pencil 📝. The columns read the registers directly.",
    "> > [!column] À faire": "> > [!column] To do",
    "> > [!column] En cours": "> > [!column] In progress",
    "> > [!column] En attente": "> > [!column] Waiting",
    "> > [!column] Terminées récemment": "> > [!column] Recently done",
    "## Historique": "## History",
    "> [!task-history]- 15 dernières clôtures": "> [!task-history]- Last 15 closed",
    "> [!help]- Les gestes utiles": "> [!help]- How to",
    "> **Terminer** : cocher la case ; la date de fin est ajoutée au registre.": "> **Finish**: tick the checkbox; the done date is added to the register.",
    "> **Commencer ou mettre en attente** : clic droit sur la case, ou crayon 📝, puis choisir l'état.":
        "> **Start or put on hold**: right-click the checkbox, or use the pencil 📝, then choose the state.",
    "> **Prioriser** : choisir une priorité avec le crayon 📝. **Planifier** indique quand travailler ; **Due / Échéance** indique quand livrer.":
        "> **Prioritise**: choose a priority with the pencil 📝. **Scheduled** says when to work on it; **Due** says when to deliver.",
    "> **Capturer sans classer** : écrire dans l'[Inbox](inbox.md), puis trier plus tard.": "> **Capture without filing**: write in the [Inbox](inbox.md), then triage it later.",
    "> Les dates simples sont lues par Tasks. Les formulations vagues restent dans le registre. Voir les [conventions](../kit/brain/docs/CONVENTIONS.md).":
        "> Plain dates are read by Tasks. Vague wordings stay in the register. See the [conventions](../kit/brain/docs/CONVENTIONS.md).",
    # The same seed lines once the inbox moved to inbox/inbox.md, and with typographic apostrophes.
    "> [Pilotage](#pilotage) · [Liste par projet](#liste-par-projet) · [Kanban](#kanban) · [Historique](#historique) · [Inbox](inbox/inbox.md)":
        "> [Focus](#focus) · [By project](#by-project) · [Kanban](#kanban) · [History](#history) · [Inbox](inbox/inbox.md)",
    "> **Capturer sans classer** : écrire dans l'[Inbox](inbox/inbox.md), puis trier plus tard.":
        "> **Capture without filing**: write in the [Inbox](inbox/inbox.md), then triage it later.",
    "> **Capturer sans classer** : écrire dans l’[Inbox](inbox/inbox.md), puis trier plus tard.":
        "> **Capture without filing**: write in the [Inbox](inbox/inbox.md), then triage it later.",
    "> [!task-focus]+ Aujourd’hui": "> [!task-focus]+ Today",
    "> Choisis jusqu’à trois actions avec le crayon 📝 : **Scheduled / Planifiée = aujourd’hui**. Les échéances du jour, les retards et les actions planifiées non terminées remontent ici.":
        "> Pick up to three actions with the pencil 📝: **Scheduled = today**. Today's due dates, overdue actions and unfinished scheduled actions show up here.",
}
QUOTE_PREFIX = re.compile(r"^((?:> ?)*)(.*)$")
WAITING_EXCLUDED = "status.name does not include attente"
WAITING = "status.name includes attente"
OPEN_TYPES = "(status.type is TODO) OR (status.type is IN_PROGRESS)"

# --- Structure: headings, front matter, header labels, tags and boilerplate lines ------------------
#
# Every table maps a French form to (English form, mark). EXACT: the current template, seed or tool writes
# this English where the earlier one wrote this French. JUDGED: an earlier format with no single
# counterpart, mapped by meaning (the reason is in the comment), or a translation with no template
# counterpart. Only whole lines (or a label at the very start of a line) match; topic headings never do.

EXACT, JUDGED = "exact", "judged"

PAGE_HEADINGS = {  # `## …` of client, mission and project pages
    "En bref": ("Summary", EXACT),
    "État actuel": ("Current state", EXACT),
    "Etat actuel": ("Current state", EXACT),
    "Lire selon le besoin": ("Read as needed", EXACT),
    "Conventions client": ("Client conventions", EXACT),
    "Registres": ("Registers", EXACT),
    "Contexte": ("Context", EXACT),
    "Liens": ("Read as needed", EXACT),  # seed setup page: « Liens » became « Read as needed »
    # The seed setup page's « État » holds Status and Goal; « Current state » is the block `timeline.py state`
    # replaces as a whole, so the bullets would be lost: the section is named after what it holds.
    "État": ("Status", JUDGED),
    "Projets liés": ("Related projects", JUDGED),  # no template section
}
MINUTES_HEADINGS = {  # `## …` of dated sources (minutes, mails, Teams, notes received)
    # The minutes template before the English one, section by section.
    "Résumé": ("Summary", EXACT),
    "Retenu": ("Key points", EXACT),
    "Décisions": ("Decisions", EXACT),
    "Actions et suivi": ("Actions and follow-up", EXACT),
    "À suivre": ("To follow", EXACT),
    "À vérifier": ("To check", EXACT),
    "Détail": ("Details", EXACT),
    "Contexte": ("Context", EXACT),
    "Points à vérifier": ("To check", EXACT),  # same role in the earlier « En bref / Sujets » format
    # The earlier « En bref / Participants / Sujets » minutes format and the messages format.
    "En bref": ("Summary", JUDGED),  # a bullet abstract, where Summary is two sentences: same role, the abstract
    "Sujets": ("Key points", JUDGED),  # per-topic facts (### per topic); Key points holds the per-topic facts
    "Faits nouveaux": ("Key points", JUDGED),  # messages format: the facts the message brings
    "Faits": ("Key points", JUDGED),
    "Points à clarifier": ("To check", JUDGED),
    "Actions": ("Actions and follow-up", JUDGED),  # new actions only; follow-ups sat in « Ce qui a changé »
    "Actions évoquées": ("Actions and follow-up", JUDGED),
    "Décisions proposées": ("Decisions", JUDGED),  # proposals only; their tag becomes « To confirm »
    "Décisions (proposées)": ("Decisions", JUDGED),
    "Décisions proposées à valider": ("Decisions", JUDGED),
    # No template section: kept as their own section, translated (« Context from memory » is the memory
    # context of a meeting, not the changes since the previous one).
    "Ce qui a changé depuis le dernier point": ("Changes since the last meeting", JUDGED),
    "Changements depuis le dernier point": ("Changes since the last meeting", JUDGED),
    "Changements depuis la dernière réunion": ("Changes since the last meeting", JUDGED),
    "Depuis la dernière réunion": ("Changes since the last meeting", JUDGED),
    "Changements depuis le dernier daily": ("Changes since the last daily", JUDGED),
    "Fiches mises à jour": ("Pages updated", JUDGED),
    "Ce qui a changé (mémoire)": ("What changed (memory)", JUDGED),
}
PERSON_HEADINGS = {  # `## …` of person pages
    "Rôle et périmètre": ("Role and scope", EXACT),
    "Ce qu'il attend": ("Expectations", EXACT),
    "Ce qu'elle attend": ("Expectations", EXACT),
    "Ce qu'il/elle attend": ("Expectations", EXACT),
    "Attentes": ("Expectations", EXACT),
    "Positions prises": ("Positions taken", EXACT),
    "Façon de travailler": ("Way of working", EXACT),
    "Historique des échanges": ("Interaction log", EXACT),
}
ADDENDUM = [  # dated addendum headings of sources (judged: no template; the dash form is already in use)
    (re.compile(r"^## Addendum du (\d{2}/\d{2}(?:/\d{4})?|\d{4}-\d{2}-\d{2})\s*$"), r"## Addendum — \1"),
    (re.compile(r"^## Addendum n°\s?(\d+) du (\d{2}/\d{2}(?:/\d{4})?|\d{4}-\d{2}-\d{2})\s*$"), r"## Addendum \1 — \2"),
]
LEFT_HEADINGS = re.compile(r"^## (Addendum (du|n°)|Changements depuis|Ce qui a changé)")  # variants listed, not converted

SOURCE_KEYS = {  # front matter of dated sources
    "titre": ("title", EXACT), "heure": ("time", EXACT), "fiabilite": ("reliability", EXACT),
    "redige_par": ("written_by", EXACT),
    "projet": ("project", JUDGED),  # internal projects; the template only has client and mission
}
RELIABILITY = {"bonne": "good", "moyenne": "medium", "faible": "low"}  # exact: the template's values

PAGE_LABELS = {  # `- **Label :**` of the header of client, mission and project pages (before the first `##`)
    "Client": ("Client", EXACT), "Status": ("Status", EXACT), "Statut": ("Status", EXACT),
    "Goal": ("Goal", EXACT), "Objectif": ("Goal", EXACT), "Suivi du temps": ("Time tracking", EXACT),
    "Time tracking": ("Time tracking", EXACT), "Repo": ("Repo", EXACT), "Repos": ("Repos", EXACT),
    "Dépôt": ("Repo", EXACT), "Dépôts": ("Repos", EXACT), "Stakeholders": ("Stakeholders", EXACT),
    "Parties prenantes": ("Stakeholders", EXACT), "Tableau": ("Board", EXACT), "Board": ("Board", EXACT),
    "Interlocuteurs": ("Contacts", EXACT), "Contacts": ("Contacts", EXACT), "Domaines": ("Domains", EXACT),
    "Domains": ("Domains", EXACT), "Actions": ("Actions", EXACT), "Sources": ("Sources", EXACT),
    "Boond": ("Boond", JUDGED),  # the time-tracking tool's name, kept: « Time tracking » would lose which tool
    "Projet parent": ("Parent project", JUDGED),
}
STATUS_VALUES = {"actif": "active", "active": "active", "en pause": "paused", "terminé": "done", "terminée": "done"}
ARCHIVED_ON = re.compile(r"^archivée? le (\d{4}-\d{2}-\d{2})$")  # judged: « archived on DATE »
PERSON_LABELS = {  # `- **Label :**` anywhere in a person page
    "Focus actuel": ("Current focus", EXACT), "Forces": ("Strengths", EXACT),
    "Axes de progression": ("Areas for progress", EXACT), "Feedback donné": ("Feedback given", EXACT),
    "Projets": ("Projects", JUDGED),  # header link list of an earlier format; the template uses `missions:`
}
LABEL_LINE = re.compile(r"^- \*\*(?P<label>[^*]+?)(?P<colon>\s*:)\*\*")

# Tags at the start of a bullet of minutes: `- **Nouvelle · ACM-001** — …`.
TAGS = {
    "Nouvelle": ("New", EXACT), "Nouveau": ("New", EXACT), "Suivi": ("Follow-up", EXACT),
    "Prise": ("Taken", EXACT), "Prises": ("Taken", EXACT), "Pris": ("Taken", EXACT),
    "Refusée": ("Rejected", EXACT), "Refusé": ("Rejected", EXACT), "Rejetée": ("Rejected", EXACT), "Rejeté": ("Rejected", EXACT),
    "À confirmer": ("To confirm", EXACT),
    "Proposée": ("To confirm", JUDGED),  # a proposal is not taken: the template's open value is « To confirm »
}
TAGS.update({word[0].lower() + word[1:]: value for word, value in list(TAGS.items())})  # the template wrote « refusée »
TAG_LINE = re.compile(r"^(?P<lead>\s*[-*] )\*\*(?P<tag>[^*·]+?)(?P<ids> · [A-Z]{2,5}-\d{3}(?:(?:, | et | and )[A-Z]{2,5}-\d{3})*)?\*\*(?=\s*[—–-])")

LINK_LABELS = [  # labels at the start of a line, followed by a link: (pattern, English, mark)
    (re.compile(r"^Fiche : (?=\[)"), "Mission page: ", EXACT),  # « Project page: » under projects/internal (judged)
    (re.compile(r"^Mission : (?=\[)"), "Mission page: ", JUDGED),
    (re.compile(r"^Projet : (?=\[)"), "Project page: ", JUDGED),
]
MARKERS = {  # whole lines of minutes, judged (no template)
    "_Vient de la mémoire._": "_From memory._",
    "_Vient de la mémoire, pas du transcript._": "_From memory, not from the transcript._",
    "_Vient de la mémoire et de l'agenda, pas du transcript._": "_From memory and the calendar, not from the transcript._",
}
BACK_TO_MISSION = re.compile(r"^\[Retour à la mission\](\([^)\s]+\))\s*$")  # exact: index template
BACK_TO_PROJECT = re.compile(r"^\[Retour au projet(?: [^\]]+)?\](\([^)\s]+\))\s*$")  # journal: exact (timeline.py); index: judged
INDEX_TYPES = {"analyse locale": "local analysis"}  # judged: `- DATE · <type> · [title](…)`
NOTE_HEADER = re.compile(r"^> Note du (\d{2}/\d{2}/\d{4}) · projet : (\[[^\]]*\]\([^)\s]*\))\s*$")  # exact: note template
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
JOURNAL_QUOTE = re.compile(  # exact: the wording of timeline.py; « de la », « du projet » are dropped from the name
    r"^> Archive du journal (?:du projet |de la |de l['’]|du |de )(?P<name>.+?) pour (?P<month>" + "|".join(MONTHS_FR)
    + r") (?P<year>\d{4}) : entrées déplacées depuis la fiche le (?P<day>\d{4}-\d{2}-\d{2})\. Les mois en cours restent dans la fiche\.\s*$")
STATE_AS_OF = re.compile(r"^> État au (\d{4}-\d{2}-\d{2}) \(([^()]*)\)\.\s*$")  # exact: timeline.py state
SEED_NAMES = {"Setup du système": "System setup"}  # exact: the seed's setup project, in titles and archive headers
GLOSSARY_TITLE = re.compile(r"^# Glossaire — ")  # exact: the pages link it as « Glossary »
INBOX_LINES = {  # exact: the French seed of inbox/inbox.md → the English seed
    "> Ton scratchpad de CAPTURE BRUTE. Balance tout ici, toute la journée, sans réfléchir à où ça va. Notes, demi-idées, rappels, liens, questions. Vitesse > structure — le bordel, c'est normal ici.":
        "> Your RAW CAPTURE scratchpad. Throw everything here, all day long, without thinking about where it goes. Notes, half-ideas, reminders, links, questions. Speed > structure — mess is normal here.",
    "> WRITE-ONLY dans la journée. On n'organise pas pendant qu'on capture. Une fois par jour, dis à l'agent « trie mon inbox » → il lit chaque ligne, la classe au bon endroit (registres d'actions / projects / people / notes), et vide ce fichier.":
        "> WRITE-ONLY during the day. Nothing gets organized while capturing. Once a day, tell the agent \"triage my inbox\" → it reads each line, files it in the right place (action registers / projects / people / notes), and empties this file.",
    "> - inbox.md = là où les pensées ATTERRISSENT (lance à incendie qu'on vide)": "> - inbox.md = where thoughts LAND (a fire hose you empty)",
    "> - state/actions.md = là où vivent les tâches, une seule fois": "> - state/actions.md = where tasks live, only once",
    "> - tasks.md = le tableau qui les affiche (plugin Tasks)": "> - tasks.md = the board that displays them (Tasks plugin)",
}


def literal(text: str) -> str:
    """A French sentence as a regex, matching straight and typographic apostrophes."""
    return re.escape(text).replace("'", "['’]")


# Guidance quotes (`> …`) of registers, pages and glossaries, sentence by sentence: a quote line is converted
# only when every one of its sentences is in the table of its kind of file; otherwise it is listed.
QUOTE_SENTENCES: dict[str, list[tuple[re.Pattern, str, str]]] = {
    "actions": [
        (literal("À copier vers `<projet>/state/actions.md` (liens écrits pour une mission client)."),
         "To copy to `<project>/state/actions.md` (links written for a client mission).", EXACT),
        (literal("Ce registre fait foi pour ID, responsable, échéance et statut ; conserver le préfixe d'ID du client, y compris entre missions."),
         "This register is authoritative for ID, owner, due date and status; keep the client's ID prefix, including across missions.", EXACT),
        (literal("Ce registre fait foi pour ID, responsable, échéance et statut ; conserver les IDs du client."),
         "This register is authoritative for ID, owner, due date and status; keep the client's IDs.", JUDGED),
        (literal("Ce registre fait foi pour ID, responsable, échéance et statut."),
         "This register is authoritative for ID, owner, due date and status.", EXACT),
        (literal("La ligne d'action garde ID, responsable, intitulé et métadonnées Tasks (priorité, `📅` échéance précise, `⏳` date de travail choisie) ; "
                 "seules les nuances d'échéance, la source et l'historique vont en sous-puces."),
         ("The action line keeps the ID, owner, title and Tasks metadata (priority, `📅` precise due date, `⏳` chosen work date); "
          "only due-date nuances, the source and the history go in sub-bullets."), EXACT),
        (literal("Ne pas dupliquer une date `📅` en sous-puce."), "Do not duplicate a `📅` date in a sub-bullet.", EXACT),
        (literal("États : `[ ]` à faire · `[/]` en cours · `[w]` en attente (relancée) · `[x]` faite · `[-]` annulée."),
         "States: `[ ]` to do · `[/]` in progress · `[w]` waiting (reminded) · `[x]` done · `[-]` cancelled.", EXACT),
        (literal("Le tableau [`tasks.md`](") + r"(?P<path>[^)\s]+)" + literal(") l'affiche avec le plugin Tasks."),
         r"The board [`tasks.md`](\g<path>) displays it with the Tasks plugin.", EXACT),
        (literal("Une action close depuis plus de 30 jours passe avec ses sous-puces dans `actions-archive-AAAA.md`, sans demander "
                 "(ID réservés ; voir `docs/CONVENTIONS.md`)."),
         ("An action closed for more than 30 days moves with its sub-bullets to `actions-archive-YYYY.md`, without asking "
          "(IDs stay reserved; see `docs/CONVENTIONS.md`)."), EXACT),
        (literal("Registre faisant foi pour les actions de maintenance du brain."), "Authoritative register for the brain's maintenance actions.", EXACT),
        (literal("Registre faisant foi pour les actions du projet ") + r"(?P<name>[^.]+)\.",
         r"Authoritative register for the actions of the \g<name> project.", JUDGED),
        (literal("Préfixe réservé : `") + r"(?P<prefix>[A-Z]{2,5})`\.", r"Reserved prefix: `\g<prefix>`.", EXACT),
    ],
    "decisions": [
        (literal("Créé par `uv run tools/brain/decision.py propose` s'il manque ; sinon à copier vers `missions/<mission>/state/decisions.md`."),
         "Created by `uv run tools/brain/decision.py propose` if missing; otherwise copy to `missions/<mission>/state/decisions.md`.", EXACT),
        (literal("Une formulation issue d'un CR ou d'un message entre ici comme proposition."),
         "A wording from minutes or a message enters here as a proposal.", EXACT),
        (literal("Seule la confirmation du propriétaire la fait passer en décision validée ; garder la source et la date du changement."),
         "Only the brain owner's confirmation turns it into an accepted decision; keep the source and the date of the change.", EXACT),
        (literal("Garder la source et le statut de chaque décision ; une décision validée ne se réécrit pas : une nouvelle la remplace."),
         "Keep the source and the status of each decision; an accepted decision is not rewritten: a new one supersedes it.", JUDGED),
        (literal("Garder la source et le statut de chaque décision."), "Keep the source and the status of each decision.", JUDGED),
        (literal("Une architecture observée dans le code n'est pas, à elle seule, une décision."),
         "An architecture observed in the code is not, on its own, a decision.", JUDGED),
        (literal("L'architecture observée dans le code n'est pas, à elle seule, une décision client."),
         "The architecture observed in the code is not, on its own, a client decision.", JUDGED),
        (literal("Une architecture déjà implémentée dans un dépôt n'est pas, à elle seule, une décision client."),
         "An architecture already implemented in a repository is not, on its own, a client decision.", JUDGED),
    ],
    "glossary": [
        (literal("Termes, acronymes et erreurs de transcription fréquentes (entre parenthèses) — sert à reconnaître la mission dans un CR ou un mail."),
         "Terms, acronyms and frequent transcription errors (in parentheses) — used to recognize the mission in minutes or a mail.", JUDGED),
    ],
    "page": [
        (literal("À copier vers `projects/clients/<client>/missions/<mission>/<mission>.md`."),
         "To copy to `projects/clients/<client>/missions/<mission>/<mission>.md`.", EXACT),
        (literal("À copier vers `projects/clients/<client>/<client>.md`."), "To copy to `projects/clients/<client>/<client>.md`.", EXACT),
        (literal("Index court : état actuel et chemins de lecture."), "Short index: current state and reading paths.", EXACT),
        (literal("Les sources datées restent dans `sources/`, les actions et décisions font foi dans `state/`."),
         "Dated sources stay in `sources/`; actions and decisions are authoritative in `state/`.", EXACT),
        (literal("Index durable du client."), "Durable index of the client.", EXACT),
        (literal("Il présente le contexte partagé et pointe vers ses missions ; les objectifs, actions, décisions et CR vivent dans chaque mission."),
         "It presents the shared context and points to its missions; goals, actions, decisions and minutes live in each mission.", EXACT),
        (literal("Projet interne dédié à l'installation, aux conventions, aux automatisations et à la maintenance de l'espace de travail."),
         "Internal project dedicated to the installation, conventions, automations and maintenance of the workspace.", EXACT),
        (literal("Index court de la mission ; les registres et sources font foi pour le détail."),
         "Short index of the mission; the registers and sources are authoritative for the detail.", JUDGED),
        (literal("Index court de la mission ; les registres, workstreams et sources font foi pour le détail."),
         "Short index of the mission; the registers, workstreams and sources are authoritative for the detail.", JUDGED),
        (literal("Index court du projet ; les registres, workstreams et sources font foi pour le détail."),
         "Short index of the project; the registers, workstreams and sources are authoritative for the detail.", JUDGED),
        (literal("L'état et les sources sont dans la mission."), "The state and the sources are in the mission.", JUDGED),
        (literal("L'état, les constats techniques et les sources vivent dans la mission."),
         "The state, the technical findings and the sources live in the mission.", JUDGED),
    ],
}
QUOTE_SENTENCES = {kind: [(re.compile(fr), en, mark) for fr, en, mark in table] for kind, table in QUOTE_SENTENCES.items()}


@dataclass
class Change:
    path: Path
    old: str
    new: str
    counts: dict[str, int] = field(default_factory=dict)
    left: list[str] = field(default_factory=list)  # « line N: reason », not converted


def count(change: Change, rule: str, n: int = 1) -> None:
    change.counts[rule] = change.counts.get(rule, 0) + n


def split(text: str) -> tuple[list[str], str]:
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.split(eol), eol


# --- Converters (text in, text out; they record counts and what they leave) ------------------------


def convert_actions(change: Change) -> None:
    lines, eol = split(change.old)
    for number, line in enumerate(lines):
        heading = re.fullmatch(r"## (.+?)\s*", line)
        if heading and heading.group(1) in ACTION_SECTIONS:
            lines[number] = f"## {ACTION_SECTIONS[heading.group(1)]}"
            count(change, "section")
            continue
        if (found := ARCHIVE_TITLE.match(line)):
            lines[number] = f"# Actions archive {found.group(1)} — {found.group(2)}"
            count(change, "archive header")
            continue
        if (found := ARCHIVE_QUOTE.match(line)):
            lines[number] = (f"> Closed actions of {found.group(1)} archived for {found.group(2)}; the live register is "
                             "[actions.md](actions.md). IDs stay reserved.")
            count(change, "archive header")
            continue
        if ACTION_LINE.match(line):
            new, n = re.subn(r"(?<!\S)#lot/", "#group/", line)
            if n:
                lines[number] = new
                count(change, "group tag", n)
            continue
        if not line.startswith("    - "):
            continue
        for rule, pattern, replacement in ACTION_RULES:
            new, n = pattern.subn(replacement, line, count=1)
            if n:
                lines[number] = new
                count(change, rule)
                break
        else:
            for pattern, reason in ACTION_LEFT:
                if pattern.match(line):
                    change.left.append(f"line {number + 1}: {reason}")
                    break
    change.new = eol.join(lines)


def convert_decisions(change: Change) -> None:
    lines, eol = split(change.old)
    section_has_block = False
    for number, line in enumerate(lines):
        if line.startswith("# Décisions — "):
            lines[number] = "# Decisions — " + line[len("# Décisions — "):]
            count(change, "title")
            continue
        heading = re.fullmatch(r"## (.+?)\s*", line)
        if heading:
            section_has_block = False
            if heading.group(1) in DECISION_SECTIONS:
                lines[number] = f"## {DECISION_SECTIONS[heading.group(1)]}"
                count(change, "section")
            continue
        if line.startswith("### "):
            section_has_block = True
            found = STATUS_TAIL.search(line)
            if found:
                value = found.group(2).strip()
                status = DECISION_STATUS.get(value, value)
                if value not in DECISION_STATUS:
                    change.left.append(f"line {number + 1}: status « {value} » kept (not a known status)")
                lines[number] = f"{line[:found.start()]}{found.group(1)}status: {status})"
                count(change, "status")
            continue
        found = FIELD_LINE.match(line)
        if found:
            label = found.group(1).strip()
            if label in DECISION_FIELDS:
                new = f"- **{DECISION_FIELDS[label]}:**{line[found.end():]}"
                if new != line:  # `**Source:**` is already English
                    lines[number] = new
                    count(change, "field")
            elif label not in DECISION_FIELDS.values():
                change.left.append(f"line {number + 1}: field « {label} » kept as written")
            continue
        if line.startswith("- ") and not section_has_block:
            change.left.append(f"line {number + 1}: decision written as a bullet, not as a ### block: kept as written")
    change.new = eol.join(lines)


def convert_page(change: Change) -> None:
    lines, eol = split(change.old)
    for number, line in enumerate(lines):
        new, n = PREVIOUS_MONTHS.subn("Previous months: ", line, count=1)
        if n:
            lines[number] = new
            count(change, "previous months")
    change.new = eol.join(lines)


def convert_person(change: Change) -> None:
    lines, eol = split(change.old)
    if not lines or lines[0].strip() != "---":
        change.left.append("no front matter: nothing converted")
        change.new = change.old
        return
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        change.left.append("unterminated front matter: nothing converted")
        change.new = change.old
        return
    present = {m.group(1) for line in lines[1:end] if (m := re.match(r"^([A-Za-z_]+)\s*:", line))}
    for number in range(1, end):
        found = re.match(r"^([A-Za-z_]+)(\s*:)", lines[number])
        if found and found.group(1) in PERSON_KEYS:
            new_key = PERSON_KEYS[found.group(1)]
            if new_key in present:
                change.left.append(f"line {number + 1}: « {found.group(1)} » kept, « {new_key} » already present")
                continue
            lines[number] = new_key + lines[number][found.end(1):]
            count(change, "front matter")
    change.new = eol.join(lines)


def convert_tasks(change: Change, labels: bool) -> None:
    lines, eol = split(change.old)
    out: list[str] = []
    block: list[tuple[str, str]] | None = None  # (quote prefix, content) of the current ```tasks block

    # The waiting status `w` was a TODO named « En attente »; it becomes the type ON_HOLD, so every query keeps its
    # meaning. It is named in the queries only before the conversion: a converted page is not touched again.
    french = any(WAITING in line or WAITING_EXCLUDED in line for line in lines)

    def flush(rows: list[tuple[str, str]]) -> None:
        excludes = any(content.strip() == WAITING_EXCLUDED for _, content in rows)
        restricted = any(content.strip() in (OPEN_TYPES, "status.type is TODO") for _, content in rows)
        for prefix, content in rows:
            if not french:
                out.append(prefix + content)
                continue
            stripped = content.strip()
            if stripped == WAITING_EXCLUDED and restricted:
                count(change, "query")  # TODO and IN_PROGRESS no longer include the waiting actions
                continue
            if stripped == WAITING:
                content = "status.type is ON_HOLD"
                count(change, "query")
            elif not excludes and stripped == OPEN_TYPES:
                content = f"{OPEN_TYPES} OR (status.type is ON_HOLD)"
                count(change, "query")
            elif not excludes and stripped == "status.type is TODO":
                content = "(status.type is TODO) OR (status.type is ON_HOLD)"
                count(change, "query")
            elif WAITING in content or WAITING_EXCLUDED in content:  # inside a longer expression
                content = content.replace(WAITING_EXCLUDED, "status.type is not ON_HOLD").replace(WAITING, "status.type is ON_HOLD")
                count(change, "query")
            elif "attente" in stripped:
                change.left.append(f"query « {stripped} » kept: it names the French status")
            out.append(prefix + content)

    for line in lines:
        prefix, content = QUOTE_PREFIX.match(line).groups()
        if block is None:
            if content.strip() == "```tasks":
                block = []
                out.append(line)
                continue
            if OLD_FORM in line:
                line = line.replace(OLD_FORM, NEW_FORM)
                count(change, "button")
            elif labels and line.rstrip() in TASKS_LINES:
                line = TASKS_LINES[line.rstrip()]
                count(change, "label")
            out.append(line)
        elif content.strip() == "```":
            flush(block)
            block = None
            out.append(line)
        else:
            block.append((prefix, content))
    if block is not None:
        flush(block)
    change.new = eol.join(out)


def convert_anchors(change: Change, source: Path, brain: Path, kit: Path) -> None:
    def fix(found: re.Match) -> str:
        target, anchor = found.group(1), found.group(2)
        resolved = (source.parent / target).resolve() if target else source
        if source.name == "README.md" and source.parent.name == "inbox" and target == "../AGENTS.md" and anchor == "ranger-linformation":
            heading = re.search(r"^## Ranger l'information", (brain / "AGENTS.md").read_text(encoding="utf-8"), re.MULTILINE) if (brain / "AGENTS.md").is_file() else None
            if heading is None:  # the seed once pointed to the brain's AGENTS.md, which never had that section
                count(change, "kit anchor")
                return f"]({os.path.relpath(kit / 'AGENTS.md', source.parent)}#where-information-goes)"
        try:
            relative = resolved.relative_to(kit)
        except ValueError:
            return found.group(0)
        new = KIT_ANCHORS.get(relative.as_posix(), {}).get(anchor)
        if new is None:
            return found.group(0)
        count(change, "kit anchor")
        return f"]({target}#{new})"
    change.new = LINK.sub(fix, change.old)


H2 = re.compile(r"## (.+?)\s*")
FENCE = re.compile(r"^\s*(?:>\s*)*(?:```|~~~)")
INDEX_TYPE = re.compile(r"^(- \d{4}-\d{2}-\d{2} · )(" + "|".join(map(re.escape, INDEX_TYPES)) + r")( · )")
QUOTE_LEFT = ("INDEX du projet", "Garder la source", "Registre faisant foi", "Ce registre fait foi", "Index court", "Index durable")


def translate_quote(text: str, table: list[tuple[re.Pattern, str, str]]) -> str | None:
    """The English of a guidance quote when each of its sentences is in `table`, else None."""
    out, position = [], 0
    while position < len(text):
        for pattern, english, _ in table:
            found = pattern.match(text, position)
            if found:
                out.append(found.expand(english))
                position = found.end()
                break
        else:
            return None
        while position < len(text) and text[position] == " ":
            position += 1
    return " ".join(out)


def status_value(rest: str) -> str:
    """The value after `**Status:**`, in English when it is one of the fixed French values."""
    value = rest.strip()
    if value in STATUS_VALUES:
        return f" {STATUS_VALUES[value]}"
    if (found := ARCHIVED_ON.match(value)):
        return f" archived on {found.group(1)}"
    return rest


def convert_source_keys(change: Change, lines: list[str], end: int) -> None:
    """Front-matter keys (and reliability values) of a dated source, lines 1 to end - 1."""
    present = {m.group(1) for line in lines[1:end] if (m := re.match(r"^([A-Za-z_]+)\s*:", line))}
    for number in range(1, end):
        found = re.match(r"^([A-Za-z_]+)\s*:", lines[number])
        if not found:
            continue
        key = found.group(1)
        if key in SOURCE_KEYS:
            new_key = SOURCE_KEYS[key][0]
            if new_key in present:
                change.left.append(f"line {number + 1}: « {key} » kept, « {new_key} » already present")
                continue
            lines[number] = new_key + lines[number][found.end(1):]
            count(change, "front matter")
            key = new_key
        if key == "reliability":
            value = re.match(r"^(reliability\s*:\s*)([\"']?)(bonne|moyenne|faible)\2(\s*)$", lines[number])
            if value:
                lines[number] = f"{value.group(1)}{value.group(2)}{RELIABILITY[value.group(3)]}{value.group(2)}{value.group(4)}"
                count(change, "front matter value")


def convert_structure(change: Change, kind: str, internal: bool, setup: bool) -> None:
    """Headings, front matter, header labels, tags and boilerplate lines of one file of the given kind."""
    lines, eol = split(change.old)
    start = 0
    if kind == "minutes" and lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            convert_source_keys(change, lines, end)
            start = end + 1
    headings = {"page": PAGE_HEADINGS, "minutes": MINUTES_HEADINGS, "person": PERSON_HEADINGS}.get(kind, {})
    present = {found.group(1) for line in lines if (found := H2.fullmatch(line))}
    header = kind == "page"  # the bullets before the first `##` of a page are its header
    fenced = False
    for number in range(start, len(lines)):
        line = lines[number]
        where = f"line {number + 1}"
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if setup and line.startswith(("# ", "> Closed actions of ")):
            for french, english in SEED_NAMES.items():
                if french in line:
                    line = lines[number] = line.replace(french, english)
                    count(change, "title")
        if kind == "glossary" and GLOSSARY_TITLE.match(line):
            lines[number] = GLOSSARY_TITLE.sub("# Glossary — ", line)
            count(change, "title")
            continue
        heading = H2.fullmatch(line)
        if heading:
            title = heading.group(1)
            header = kind == "page" and title in ("État", "Status")  # the seed setup page keeps its header fields there
            new = f"## {headings[title][0]}" if title in headings else None
            if new is None and kind == "minutes":
                for pattern, replacement in ADDENDUM:
                    if pattern.match(line):
                        new = pattern.sub(replacement, line).rstrip()
                        break
                else:
                    if LEFT_HEADINGS.match(line):
                        change.left.append(f"{where}: heading « {title} » kept (a variant that is not in the mapping)")
            if new is not None:
                english = new[3:]
                if english in present:
                    change.left.append(f"{where}: heading « {title} » kept, « {english} » is already in the file")
                else:
                    lines[number] = new
                    present.add(english)
                    count(change, "heading")
            continue
        if kind in ("page", "person") and (found := LABEL_LINE.match(line)):
            labels = PAGE_LABELS if kind == "page" else PERSON_LABELS
            label = found.group("label").strip()
            if label in labels and (header or kind == "person"):
                english = labels[label][0]
                rest = line[found.end():]
                if english != label or found.group("colon") != ":":
                    count(change, "header label" if kind == "page" else "person label")
                if english == "Status" and (value := status_value(rest)) != rest:
                    rest = value
                    count(change, "status value")
                lines[number] = f"- **{english}:**{rest}"
            continue
        if line.startswith("> ") and kind in QUOTE_SENTENCES:
            if kind == "page" and (found := STATE_AS_OF.match(line)):
                lines[number] = f"> As of {found.group(1)} ({found.group(2)})."
                count(change, "boilerplate")
                continue
            text = line[2:].rstrip()
            english = translate_quote(text, QUOTE_SENTENCES[kind])
            if english is not None:
                lines[number] = f"> {english}"
                count(change, "boilerplate")
            elif text.startswith(QUOTE_LEFT):
                change.left.append(f"{where}: guidance quote mixes boilerplate with page-specific text, translate it by hand")
            continue
        if kind == "minutes":
            found = TAG_LINE.match(line)
            if found and found.group("tag").strip() in TAGS:
                ids = (found.group("ids") or "").replace(" et ", " and ")
                lines[number] = f"{found.group('lead')}**{TAGS[found.group('tag').strip()][0]}{ids}**{line[found.end():]}"
                count(change, "tag")
                continue
            for pattern, english, _ in LINK_LABELS:
                if pattern.match(line):
                    if english == "Mission page: " and internal:
                        english = "Project page: "
                    lines[number] = pattern.sub(english, line, count=1)
                    count(change, "link label")
                    break
            else:
                if line.strip() in MARKERS:
                    lines[number] = MARKERS[line.strip()]
                    count(change, "boilerplate")
            continue
        if kind in ("index", "journal"):
            if kind == "index" and (found := BACK_TO_MISSION.match(line)):
                lines[number] = f"[Back to the mission]{found.group(1)}"
                count(change, "back link")
            elif (found := BACK_TO_PROJECT.match(line)):
                lines[number] = f"[{'Back to the project' if kind == 'index' else 'Back to project'}]{found.group(1)}"
                count(change, "back link")
            elif kind == "index" and (found := INDEX_TYPE.match(line)):
                lines[number] = found.group(1) + INDEX_TYPES[found.group(2)] + found.group(3) + line[found.end():]
                count(change, "index type")
            elif kind == "journal" and (found := JOURNAL_QUOTE.match(line)):
                name = SEED_NAMES.get(found.group("name"), found.group("name")) if setup else found.group("name")
                month = MONTHS_EN[MONTHS_FR.index(found.group("month"))]
                lines[number] = (f"> Journal archive of {name} for {month} {found.group('year')}: entries moved from the project page "
                                 f"on {found.group('day')}. The current month stays on the page.")
                count(change, "boilerplate")
            continue
        if kind == "note":
            if (found := NOTE_HEADER.match(line)):
                lines[number] = f"> Note from {found.group(1)} · project: {found.group(2)}"
                count(change, "boilerplate")
            elif line.startswith("> Note du "):
                change.left.append(f"{where}: note header with extra text, translate it by hand")
            continue
        if kind == "inbox" and line.rstrip() in INBOX_LINES:
            lines[number] = INBOX_LINES[line.rstrip()]
            count(change, "boilerplate")
    change.new = eol.join(lines)


def structure_files(brain: Path) -> list[tuple[Path, str, bool, bool]]:
    """(path, kind, internal project, setup project) of every file the structure pass reads."""
    found: list[tuple[Path, str, bool, bool]] = []
    projects = brain / "projects"
    for path in sorted(projects.rglob("*.md")) if projects.is_dir() else []:
        if path.is_symlink():
            continue
        parts = path.relative_to(projects).parts
        folders = parts[:-1]
        kind = None
        if "sources" in folders:
            at = folders.index("sources")
            if len(folders) == at + 2 and re.fullmatch(r"\d{4}-\d{2}", folders[at + 1]):
                if path.name == "index.md":
                    kind = "index"
                elif re.match(r"\d{4}-\d{2}-\d{2}-[a-z]+-", path.name):
                    kind = "minutes"
        elif "journal" in folders:
            kind = "journal" if folders[-1] == "journal" and re.fullmatch(r"\d{4}-\d{2}\.md", path.name) else None
        elif "notes" in folders:
            kind = "note" if folders[-1] == "notes" else None
        elif any(part in ("workstreams", "handoffs", "scripts") for part in folders):
            kind = None
        elif folders and folders[-1] == "state":
            if path.name == "actions.md" or re.fullmatch(r"actions-archive-\d{4}\.md", path.name):
                kind = "actions"
            elif path.name in ("decisions.md", "glossary.md"):
                kind = path.stem if path.stem == "glossary" else "decisions"
        elif path.stem == path.parent.name:
            kind = "page"
        if kind:
            internal = parts[0] == "internal" or (parts[0] == "archive" and len(parts) > 1)
            found.append((path, kind, internal, parts[:2] == ("internal", "setup")))
    people = brain / "people"
    for path in sorted(people.rglob("*.md")) if people.is_dir() else []:
        if path.name != "README.md" and not path.name.startswith("_") and not path.is_symlink():
            found.append((path, "person", False, False))
    if (brain / "inbox" / "inbox.md").is_file():
        found.append((brain / "inbox" / "inbox.md", "inbox", False, False))
    return found


def mapping_rows() -> list[tuple[str, str, str, str]]:
    """(category, French, English, mark) of every structure table, for --mapping."""
    rows = []
    for category, table in (("page heading", PAGE_HEADINGS), ("minutes heading", MINUTES_HEADINGS),
                            ("person heading", PERSON_HEADINGS), ("source front matter", SOURCE_KEYS),
                            ("page header label", PAGE_LABELS), ("person label", PERSON_LABELS), ("minutes tag", TAGS)):
        rows += [(category, french, english, mark) for french, (english, mark) in table.items()]
    rows += [("decision field", french, english, EXACT if french not in ("Suite", "Source et validation") else JUDGED)
             for french, english in DECISION_FIELDS.items() if french != english]
    rows += [("reliability value", french, english, EXACT) for french, english in RELIABILITY.items()]
    rows += [("status value", french, english, EXACT) for french, english in STATUS_VALUES.items() if french != english]
    rows += [("status value", "archivé le DATE", "archived on DATE", JUDGED), ("addendum heading", "## Addendum du DATE", "## Addendum — DATE", JUDGED),
             ("addendum heading", "## Addendum n°N du DATE", "## Addendum N — DATE", JUDGED)]
    rows += [("link label", pattern.pattern.split(" : ")[0].lstrip("^") + " :", english.strip(), mark) for pattern, english, mark in LINK_LABELS]
    rows += [("link label", "Fiche : (under projects/internal)", "Project page:", JUDGED)]
    rows += [("minutes marker", french, english, JUDGED) for french, english in MARKERS.items()]
    rows += [("back link", "[Retour à la mission]", "[Back to the mission]", EXACT), ("back link", "[Retour au projet] (journal)", "[Back to project]", EXACT),
             ("back link", "[Retour au projet …] (index)", "[Back to the project]", JUDGED)]
    rows += [("index type", french, english, JUDGED) for french, english in INDEX_TYPES.items()]
    rows += [("boilerplate", "> Archive du journal de N pour <mois> AAAA : …", "> Journal archive of N for <Month> YYYY: …", EXACT),
             ("boilerplate", "> État au DATE (MODEL).", "> As of DATE (MODEL).", EXACT),
             ("boilerplate", "> Note du DATE · projet : [L](U)", "> Note from DATE · project: [L](U)", EXACT),
             ("title", "# Glossaire — ", "# Glossary — ", EXACT)]
    rows += [("seed name", french, english, EXACT) for french, english in SEED_NAMES.items()]
    rows += [("inbox seed line", french, english, EXACT) for french, english in INBOX_LINES.items()]
    for kind, table in QUOTE_SENTENCES.items():
        rows += [(f"{kind} quote sentence", re.sub(r"\\(.)", r"\1", pattern.pattern.replace("['’]", "'")), english, mark)
                 for pattern, english, mark in table]
    return rows


def convert_json(change: Change, kind: str) -> None:
    """Rename the French keys and values of a .data JSON file in its text, so its layout is kept."""
    text = change.old
    if kind == "transcripts":
        text, n = re.subn(r'"date_traitement"(\s*:)', r'"processed_on"\1', text)
        if n:
            count(change, "key", n)
        mapping, key = TRANSCRIPT_STATUS, "status"
    elif kind == "messages":
        mapping, key = MESSAGE_STATUS, "status"
    else:
        mapping, key = SCOPES, "scope"
    for old, new in mapping.items():
        text, n = re.subn(rf'("{key}"\s*:\s*)"{re.escape(old)}"', rf'\1"{new}"', text)
        if n:
            count(change, "value", n)
    if text != change.old:  # the rewrite must be exactly the intended data change
        expected = rename_data(json.loads(change.old), kind)
        if json.loads(text) != expected:
            raise ValueError(f"{change.path}: unexpected JSON rewrite, nothing written")
    change.new = text


def rename_data(data: object, kind: str) -> object:
    if kind == "brain" and isinstance(data, dict):
        return {**data, "scope": SCOPES.get(data.get("scope"), data.get("scope"))} if "scope" in data else data
    mapping = TRANSCRIPT_STATUS if kind == "transcripts" else MESSAGE_STATUS

    def walk(value: object) -> object:
        if isinstance(value, dict):
            renamed = {("processed_on" if kind == "transcripts" and k == "date_traitement" else k): walk(v) for k, v in value.items()}
            if isinstance(renamed.get("status"), str):
                renamed["status"] = mapping.get(renamed["status"], renamed["status"])
            return renamed
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value
    return walk(data)


# --- Brain walk ----------------------------------------------------------------------------------


def project_files(brain: Path) -> list[Path]:
    """Markdown files of projects/ that may hold a format, outside the folders that are never written."""
    found = []
    for path in sorted((brain / "projects").rglob("*.md")):
        parts = path.relative_to(brain / "projects").parts
        if any(part in NEVER for part in parts[:-1]) or path.is_symlink():
            continue
        found.append(path)
    return found


def plan(brain: Path, labels: bool = True) -> list[Change]:
    kit = (brain.parent / "kit/brain").resolve()
    changes: dict[Path, Change] = {}

    def change_of(path: Path) -> Change:
        if path not in changes:
            text = path.read_bytes().decode("utf-8")
            changes[path] = Change(path, text, text)
        return changes[path]

    def apply(path: Path, convert, *extra) -> None:
        change = change_of(path)
        before = change.old
        change.old = change.new
        convert(change, *extra)
        change.old = before

    for path in project_files(brain):
        if path.parent.name == "state" and (path.name == "actions.md" or re.fullmatch(r"actions-archive-\d{4}\.md", path.name)):
            apply(path, convert_actions)
        elif path.parent.name == "state" and path.name == "decisions.md":
            apply(path, convert_decisions)
        elif path.stem == path.parent.name:
            apply(path, convert_page)
    for path in sorted((brain / "people").rglob("*.md")) if (brain / "people").is_dir() else []:
        if path.name != "README.md" and not path.name.startswith("_") and not path.is_symlink():
            apply(path, convert_person)
    if (brain / "tasks.md").is_file():
        apply(brain / "tasks.md", convert_tasks, labels)
    for path in [brain / "README.md", brain / "AGENTS.md", brain / "inbox" / "README.md", *sorted((brain / "docs").glob("*.md")),
                 *project_files(brain)]:
        if path.is_file():
            apply(path, convert_anchors, path, brain, kit)
    for name, kind in (("transcripts.json", "transcripts"), ("messages-state.json", "messages"), ("brain.json", "brain")):
        path = brain / ".data" / name
        if path.is_file():
            apply(path, convert_json, kind)
    for path, kind, internal, setup in structure_files(brain):
        apply(path, convert_structure, kind, internal, setup)
    return [change for change in changes.values() if change.new != change.old or change.left]


def dirty(brain: Path, paths: list[Path]) -> tuple[set[Path], str]:
    """Files that must not be written, and why: uncommitted changes, or all of them outside a Git repository."""
    result = subprocess.run(["git", "-C", str(brain), "status", "--porcelain", "-z", "--", *map(str, paths)],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        return {path.resolve() for path in paths}, "not a Git repository, use --allow-dirty"
    return {(brain / entry[3:]).resolve() for entry in filter(None, result.stdout.split("\0"))}, "uncommitted changes"


def write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.migrate-{os.getpid()}")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a brain's French format labels to English (dry run by default).")
    parser.add_argument("--brain", type=Path, metavar="PATH", help="brain to convert (default: BRAIN_DIR, else the default brain of Work)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="apply the changes")
    mode.add_argument("--check", action="store_true", help="exit 1 when something is left to convert")
    parser.add_argument("--diff", action="store_true", help="print the unified diff of each file")
    parser.add_argument("--allow-dirty", action="store_true", help="also write files with uncommitted changes")
    parser.add_argument("--no-tasks-labels", action="store_true", help="keep the French titles and help of tasks.md")
    parser.add_argument("--mapping", action="store_true", help="print the structure mapping table (exact or judged) and exit")
    args = parser.parse_args()
    if args.mapping:
        for category, french, english, mark in mapping_rows():
            print(f"{mark}\t{category}\t{french}\t→\t{english}")
        return 0
    brain = (args.brain or BRAIN).expanduser().resolve()
    if not (brain / "projects").is_dir():
        print(f"error: no projects/ under {brain}", file=sys.stderr)
        return 2
    try:
        changes = plan(brain, labels=not args.no_tasks_labels)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    pending = [change for change in changes if change.new != change.old]
    blocked, why = dirty(brain, [change.path for change in pending]) if args.write and not args.allow_dirty else (set(), "")
    total = 0
    by_rule: dict[str, int] = {}
    for change in changes:
        name = change.path.relative_to(brain).as_posix()
        n = sum(change.counts.values())
        total += n
        for rule, k in change.counts.items():
            by_rule[rule] = by_rule.get(rule, 0) + k
        if n:
            detail = ", ".join(f"{rule} {k}" for rule, k in sorted(change.counts.items()))
            state = f"refused ({why})" if change.path.resolve() in blocked else ("written" if args.write else "to convert")
            print(f"{name}: {n} change(s), {state} — {detail}")
        for left in change.left:
            print(f"{name}: left as is — {left}")
        if args.diff and change.new != change.old:
            sys.stdout.writelines(difflib.unified_diff(change.old.splitlines(keepends=True), change.new.splitlines(keepends=True),
                                                       f"a/{name}", f"b/{name}"))
    if args.write:
        for change in pending:
            if change.path.resolve() not in blocked:
                write(change.path, change.new)
    verb = "written" if args.write else "to convert"
    if by_rule:
        print("By rule: " + ", ".join(f"{rule} {k}" for rule, k in sorted(by_rule.items())))
    left = sum(len(change.left) for change in changes)
    if left:
        print(f"Left as is: {left} line(s) or file(s), listed above")
    print(f"Total: {total} change(s) {verb} in {len(pending) - len(blocked)} file(s)"
          + (f"; {len(blocked)} file(s) refused, commit or set them aside first" if blocked else ""))
    if blocked:
        return 1
    return 1 if args.check and pending else 0


if __name__ == "__main__":
    sys.exit(main())
