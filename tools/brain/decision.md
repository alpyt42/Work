# Decision tool

`tools/brain/decision.py` is the only tool that writes to the decision registers (`projects/**/state/decisions.md`, next to the project's `actions.md`). It reuses `action.py` (project resolution, atomic write, dates, text validation). A decision is therefore always written the same way:

```markdown
### 12. Decision title (2026-10-13, status: proposed)
- **Context:** …
- **Decision:** …
- **Consequences:** …
- **Source:** [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-daily-migration.md)
- **Accepted:** Owner, 2026-10-14.
```

- The register has three sections: `## Proposed`, `## Accepted`, `## Rejected / superseded`. A proposal is appended at the end of `Proposed`; an accepted, rejected or superseded decision moves to the **top** of its section (most recent first).
- Existing blocks vary (status missing from the title, `active`, `superseded`, `Follow-up` and `Superseded by` fields, `Source and validation`): the tool reads them as they are and only rewrites the block it moves. The content of an accepted decision is never rewritten; a new decision supersedes it.
- **Number**: `12.` at the start of the heading, given once by `propose` (the highest number of the register plus one) and never changed: a decision keeps it when it is accepted, rejected or superseded, and a number is never reused, since a decision is never deleted. Pages, timeline entries and other decisions cite a decision by it (« décision 12 » in a French page), within its project. A heading without a number (a register written before numbers were stored, a block added by hand) reads as the highest written number plus one, in file order; in a register without any number that is its rank, the number it was cited by until then. The next write to the register (`propose`, `accept`, `reject`, `supersede`) first writes those numbers into the headings, its JSON giving how many in `numbered`; `number --write` does it for every live register at once. A heading written by hand whose title starts with a number and a dot (`### 2. Phase two (…)`) reads as decision 2: before the first write, reword such a title (`Phase two`) or give it its number in front (`### 2. 2. Phase two`).
- A brain written with the earlier French labels is converted once with `uv run tools/brain/migrate-english.py` (dry run by default, `--write` to apply it).

## Commands

From the Work root; the output is JSON, except the text of `list --table` and `show --text` (exit codes: 0 done, 2 invalid request, 3 not found, 4 conflict or ambiguous reference).

```sh
uv run tools/brain/decision.py list --project acme/demo --state proposed --table
uv run tools/brain/decision.py show 12 --project acme/demo
uv run tools/brain/decision.py show 12 --project acme/demo --text   # compact text, to read a decision
uv run tools/brain/decision.py propose --project acme/demo --title "Recorded demo" \
    --decision "Recorded video rather than a live demo." --context "Risk of AWS access." \
    --source "[Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)" --date 2026-10-13
uv run tools/brain/decision.py accept "Recorded demo" --project acme/demo --on 2026-10-14 --note "in committee"
uv run tools/brain/decision.py reject 12 --project acme/demo --reason "out of scope"
uv run tools/brain/decision.py supersede "Workshop schedule" --by "Corrected schedule" --project acme/demo
uv run tools/brain/decision.py number            # report the headings still without a number
uv run tools/brain/decision.py number --write    # write them, in every live register
```

- `list`: every project by default; `--state proposed|accepted|rejected|all` (earlier name: `--status`; the section is authoritative, not the status text); `--table` for one line per decision.
- `REF`: number of the decision in that project (the one `list` gives and its heading carries), or a case-insensitive substring of the title. Several decisions match, or a number is written in two headings: exit code 4 with the candidates; none: exit code 3.
- `show REF --project P --text`: the decision as plain text, once, to read it without the JSON (which gives its fields twice, in `fields` and in `block`). First `no. N [state] date — title  (project)`, where the state is the section the decision sits in, followed by `, status: …` when the title says something else (`active`, `superseded`); then its fields as written; last, the `file:line` of the decision from the Work root. An error stays JSON. The JSON of `show` is unchanged.

  ```text
  no. 12 [accepted] 2026-10-13 — Recorded demo  (acme / demo)
  - **Context:** Risk of AWS access.
  - **Decision:** Recorded video rather than a live demo.
  - **Source:** [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)
  - **Accepted:** Owner, 2026-10-14 (in committee).
  brain/projects/clients/acme/missions/demo/state/decisions.md:31
  ```
- `propose`: `--title`, `--decision`, `--source` required; `--context`, `--consequences`, `--date` (default: today, Paris time) optional. Creates `state/decisions.md` (title, quote, three sections) if it is missing. Refuses a title that is already present. Gives the decision the highest number of the register plus one, returned in `number` and in its `label` (`proposal no. 13 “…”`): cite it by that number.
- **Cap**: the title, context, decision and consequences hold 70 words at most together, the source apart (words between spaces, a link counting as its label). `propose` refuses a longer decision (exit code 2), even with `--dry-run`: say what was decided, link the source once, and write a context only when the source does not give it. `accept`, `reject` and `supersede` write no new title or text and have no cap.
- `accept`: only a proposed decision. Status `accepted` in the title (added if it was missing), line `- **Accepted:** OWNER, DATE.` (`--by`, `--note`).
- `reject`: only a proposed decision. Status `rejected`, line `- **Rejected:** OWNER, DATE (reason).` (`--by`, `--reason`). Without `--by`, the name comes from `BRAIN_OWNER` or from `owner` in `<brain>/.data/doctor.json`.
- `supersede OLD --by NEW`: OLD (proposed or accepted) moves to the top of `Rejected / superseded`, status `superseded`, line `- **Superseded by:** “title of NEW” (DATE).`; NEW stays in place.
- `number [--project P] [--write]`: writes its number into every decision heading that has none, in one project or in every live one (archived projects are left as they are), without moving anything; a dry run without `--write`. One JSON item per register concerned: `numbered` (headings numbered), `first` and `last` (their numbers), `duplicates` (numbers written in two headings, after a hand copy or a merge: give the later one the next free number by hand). An empty list: nothing to do.
- `--project` accepts the same forms as `action.py` (register path, project folder, `client/mission`, label).
- **Archived projects** (moved by `uv run tools/brain/brain-state.py archive`): `list` leaves them out; `list --archived` brings them back, their decisions flagged `"project_archived": true` (`, archived` after the project in `--table`), and lets `--project` name one. `propose`, `accept`, `reject` and `supersede` refuse them (exit code 2: unarchive first); `show` still reads them, flagged `"project_archived": true` (`(archived project)` after the `file:line` of `--text`).
- Every write but `number` accepts `--dry-run` and returns a readable `label` with the resulting block, the decision's `number` and `numbered` (headings numbered in passing).
- `--brain PATH` or `BRAIN_DIR` for another brain than the default brain of Work (see [tools/README.md](../README.md)); `ACTION_NOW="YYYY-MM-DD HH:MM"` freezes the clock (tests).

## When the agent uses it

- Minutes or a message review that surfaces a decision **proposes** it with `propose` (source required); the agent does not accept it.
- Only the brain's owner has a decision accepted, rejected or superseded: `accept`, `reject` and `supersede` run on their explicit request, with the date of their decision (`--on`).
- To read the state of a project's decisions: `list --table` then `show REF --text`, never a hand reading of the file to infer a status; `uv run tools/brain/brain-state.py find <term>` gives the number of the decisions that mention a topic.
- To cite a decision in a page, a timeline entry, minutes or another decision: its number, from `list`, `show` or the `propose` result (« décision 12 »), never a number counted by hand in the file.

## Guarantees

- Atomic writes; refused (exit code 4) if the register changed between the read and the write.
- Only the moved block and the blank lines at its two joins change, plus the headings still without a number, which get theirs; line endings and final newline preserved.
- A decision's number never changes: moving a block renumbers nothing.
- Entries must fit on one line, with no reserved separator, with real dates (`YYYY-MM-DD`).
