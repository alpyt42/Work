# Decision tool

`tools/brain/decision.py` is the only tool that writes to the decision registers (`projects/**/state/decisions.md`, next to the project's `actions.md`). It reuses `action.py` (project resolution, atomic write, dates, text validation). A decision is therefore always written the same way:

```markdown
### Decision title (2026-10-13, status: proposed)
- **Context:** …
- **Decision:** …
- **Consequences:** …
- **Source:** [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-daily-migration.md)
- **Accepted:** Owner, 2026-10-14.
```

- The register has three sections: `## Proposed`, `## Accepted`, `## Rejected / superseded`. A proposal is appended at the end of `Proposed`; an accepted, rejected or superseded decision moves to the **top** of its section (most recent first).
- Existing blocks vary (status missing from the title, `active`, `superseded`, `Follow-up` and `Superseded by` fields, `Source and validation`): the tool reads them as they are and only rewrites the block it moves. The content of an accepted decision is never rewritten; a new decision supersedes it.
- **Number**: rank of the decision in the project's register (1..n, in file order). It changes when a decision changes section: run `list` again before using it.
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
```

- `list`: every project by default; `--state proposed|accepted|rejected|all` (earlier name: `--status`; the section is authoritative, not the status text); `--table` for one line per decision.
- `REF`: number from the `list` of that project, or a case-insensitive substring of the title. Several decisions match: exit code 4 with the list of candidates; none: exit code 3.
- `show REF --project P --text`: the decision as plain text, once, to read it without the JSON (which gives its fields twice, in `fields` and in `block`). First `no. N [state] date — title  (project)`, where the state is the section the decision sits in, followed by `, status: …` when the title says something else (`active`, `superseded`); then its fields as written; last, the `file:line` of the decision from the Work root. An error stays JSON. The JSON of `show` is unchanged.

  ```text
  no. 12 [accepted] 2026-10-13 — Recorded demo  (acme / demo)
  - **Context:** Risk of AWS access.
  - **Decision:** Recorded video rather than a live demo.
  - **Source:** [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)
  - **Accepted:** Owner, 2026-10-14 (in committee).
  brain/projects/clients/acme/missions/demo/state/decisions.md:31
  ```
- `propose`: `--title`, `--decision`, `--source` required; `--context`, `--consequences`, `--date` (default: today, Paris time) optional. Creates `state/decisions.md` (title, quote, three sections) if it is missing. Refuses a title that is already present.
- **Cap**: the title, context, decision and consequences hold 70 words at most together, the source apart (words between spaces, a link counting as its label). `propose` refuses a longer decision (exit code 2), even with `--dry-run`: say what was decided, link the source once, and write a context only when the source does not give it. `accept`, `reject` and `supersede` write no new title or text and have no cap.
- `accept`: only a proposed decision. Status `accepted` in the title (added if it was missing), line `- **Accepted:** OWNER, DATE.` (`--by`, `--note`).
- `reject`: only a proposed decision. Status `rejected`, line `- **Rejected:** OWNER, DATE (reason).` (`--by`, `--reason`). Without `--by`, the name comes from `BRAIN_OWNER` or from `owner` in `<brain>/.data/doctor.json`.
- `supersede OLD --by NEW`: OLD (proposed or accepted) moves to the top of `Rejected / superseded`, status `superseded`, line `- **Superseded by:** “title of NEW” (DATE).`; NEW stays in place.
- `--project` accepts the same forms as `action.py` (register path, project folder, `client/mission`, label).
- **Archived projects** (moved by `uv run tools/brain/brain-state.py archive`): `list` leaves them out; `list --archived` brings them back, their decisions flagged `"project_archived": true` (`, archived` after the project in `--table`), and lets `--project` name one. `propose`, `accept`, `reject` and `supersede` refuse them (exit code 2: unarchive first); `show` still reads them, flagged `"project_archived": true` (`(archived project)` after the `file:line` of `--text`).
- Every write accepts `--dry-run` and returns a readable `label` with the resulting block.
- `--brain PATH` or `BRAIN_DIR` for another brain than the default brain of Work (see [tools/README.md](../README.md)); `ACTION_NOW="YYYY-MM-DD HH:MM"` freezes the clock (tests).

## When the agent uses it

- Minutes or a message review that surfaces a decision **proposes** it with `propose` (source required); the agent does not accept it.
- Only the brain's owner has a decision accepted, rejected or superseded: `accept`, `reject` and `supersede` run on their explicit request, with the date of their decision (`--on`).
- To read the state of a project's decisions: `list --table` then `show REF --text`, never a hand reading of the file to infer a status; `uv run tools/brain/brain-state.py find <term>` gives the number of the decisions that mention a topic.

## Guarantees

- Atomic writes; refused (exit code 4) if the register changed between the read and the write.
- Only the moved block and the blank lines at its two joins change; line endings and final newline preserved.
- Entries must fit on one line, with no reserved separator, with real dates (`YYYY-MM-DD`).
