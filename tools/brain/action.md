# Action tool

`tools/brain/action.py` is the only tool that writes to the action registers (`projects/**/state/actions.md`). Agents call it from the command line. The local `tasks-web` interface runs it for each of its writes and imports its code to read. An action is therefore always written the same way:

```markdown
- [ ] **DEM-101** — Owner — Title ⏫ ➕ 2026-10-13 📅 2026-10-20
    - [x] First step ✅ 2026-10-14
    - [ ] Second step
    - source: [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)
    - created: 2026-10-13 14:32
    - updated: 2026-10-14 09:05
    - 14/10: history entry
```

(`cr` in a source file name means meeting minutes: `YYYY-MM-DD-cr-<slug>.md`.) States: `[ ]` to do, `[/]` in progress, `[w]` waiting, `[x]` done, `[-]` cancelled. Sections: `## Open`, `## Done`, `## Cancelled`.

A brain written with the earlier French labels is converted once with `uv run tools/brain/migrate-english.py` (dry run by default, `--write` to apply it).

- **Creation**: `➕ YYYY-MM-DD` on the line (read by the Tasks plugin, which only knows dates) and `created: YYYY-MM-DD HH:MM` as a sub-bullet (Paris time, to the minute, no seconds). Set once, at creation.
- **Update**: `updated: YYYY-MM-DD HH:MM` (Paris time, to the minute), set only when a change made with the tool really changes the action (fields, status, adding, editing or removing history). The semantic task is its line and all its sub-bullets except `updated:`, with trailing spaces ignored. That task is compared with the last Git synchronization point: the merge base of `HEAD` and its upstream branch, or `HEAD` when no upstream is configured.
    1. the task is exactly as at that synchronization point (`git show <reference>:`, wherever it sits in the register): it gets back the `updated:` of that version, or none if that version had none;
    2. otherwise, the action is as it was before the write (the same status set again, a note edited to the same text): the previous `updated:` stays, and when the whole register is unchanged the file is not rewritten;
    3. otherwise the current time is stamped.

  This single comparison covers any combination of fields and history: changing then restoring a status, date, title or note, repairing a stale stamp left by an earlier edit, and returning past unsent local commits. Without a Git repository, or when Git cannot read the reference, the file or the action, only 2 and 3 apply. `move` always stamps (it adds a history entry); `sweep` and `archive` move the block as it is and never touch `updated:`; `created:` is never rewritten. The JSON of `update` and `history` carries `updated_changed` (whether the `updated:` sub-bullet differs after the write).
- **Due date**: `📅 YYYY-MM-DD` on the line when it is known; a nuanced due date ("before…") goes in a `due:` sub-bullet.
- **Closure**: `✅ YYYY-MM-DD` (done) or `❌ YYYY-MM-DD` (cancelled) on the line; the evidence goes in a `done: <evidence>` sub-bullet, or `cancelled: YYYY-MM-DD by <person> — [source](…)`.
- **Group**: an optional label, not a parent task. At most one `#group/<slug>` tag at the end of the title, just before the Tasks emojis: `- [ ] **DEM-097** — Owner — Plan the workshop #group/demo-workshop ➕ 2026-10-12 📅 2026-10-20`. Slug `[a-z0-9]+(-[a-z0-9]+)*`, 40 characters at most; the interface displays it as "Demo workshop". An action without a tag stays valid and is never modified when another field is rewritten. The tag is written with `--group`, not by hand in `--title`.
- **History**: one `DD/MM: …` sub-bullet per change of state, owner, due date or blocker, 35 words at most (a link counts as its label). `history add` and `history edit` refuse a longer text (exit code 2): write the change, link the source once, the detail stays in the source. The `moved from …` entry that `move` writes itself is exempt; `update` writes none. A text that starts with the entry's own date (`13/10: …` or `13/10 : …`) loses it; another date is refused (exit code 2: give it with `--date`). `history add` of an entry the block already holds, same date and same text, writes nothing and answers `"unchanged": true`.
- The `source`, `created` and `updated` sub-bullets cannot be removed with `history remove`. Actions older than 2026-10-13 do not have these dates: they are not invented.

## Commands

From the Work root; the output is JSON, except the text of `list --table` and `show --text` (exit codes: 0 done, 2 invalid request, 3 not found, 4 conflict).

```sh
uv run tools/brain/action.py list --project acme/demo --table
uv run tools/brain/action.py board                    # complete view by project (terminal)
uv run tools/brain/action.py board --write --watch    # agents/tasks-board.md kept up to date (VS Code preview)
uv run tools/brain/action.py show DEM-099             # JSON, read by tasks-web
uv run tools/brain/action.py show DEM-099 --text      # compact text, to read an action: the last 3 history entries (--last N, 0 for all)
uv run tools/brain/action.py create --project acme/demo --title "Follow up with the contact" \
    --owner Owner --source "[Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)" --due 2026-10-20
uv run tools/brain/action.py update DEM-099 --state done --closed-on 2026-10-14
uv run tools/brain/action.py update DEM-099 --group demo-workshop   # --group "" removes the group
uv run tools/brain/action.py history add DEM-099 --text "followed up by mail" --date 2026-10-14
uv run tools/brain/action.py history edit DEM-099 --index 3 --text "followed up by mail and chat"
uv run tools/brain/action.py history remove DEM-099 --index 3
uv run tools/brain/action.py subtask add DEM-099 --text "Book the room"          # --position N to insert it
uv run tools/brain/action.py subtask toggle DEM-099 --index 0                    # --done / --undone to force a state
uv run tools/brain/action.py subtask edit DEM-099 --index 0 --text "Book the large room"
uv run tools/brain/action.py subtask move DEM-099 --index 2 --to 0
uv run tools/brain/action.py subtask remove DEM-099 --index 1
uv run tools/brain/action.py move DEM-099 --to acme/other-mission
uv run tools/brain/action.py check                    # register format (exit code 1 on error)
uv run tools/brain/action.py delete DEM-099
uv run tools/brain/action.py sweep --write            # puts each action under the section of its state
uv run tools/brain/action.py archive --write          # archives closures older than 30 days
uv run tools/brain/action.py sweep --archive --write  # both, sweep first
```

- `--project` accepts the register path, the project folder, `client/mission`, the name of an internal project or the board label (`acme / demo`).
- **Archived projects** (moved whole into the `archive/` folder at their level by `uv run tools/brain/brain-state.py archive`: `projects/clients/<client>/missions/archive/<mission>/`, `projects/internal/archive/<project>/`, `projects/clients/archive/<client>/` for a whole client; the earlier `projects/archive/` and `projects/clients/<client>/archive/` still count) keep their label (`acme / demo`) and are out of the context. `list`, `board`, `sweep`, `archive` and `check` leave them out; `list --archived` brings them back (their actions carry `"project_archived": true`, `(project, archived)` in `--table`) and lets `--project` name one; `check --archived`, or a `--register` that names one, checks their format. Their IDs always count: `check` reports a live action that reuses one, `create` numbers after them. `create`, `update`, `history`, `subtask`, `move` (from or to one) and `delete` refuse an action of an archived project (exit code 2, with the `unarchive` command to run first); `show` still reads it, flagged `"project_archived": true` (`(archived project)` on the last line of `--text`).
- `create`: ID following the highest found in the whole client or project folder, sources included; appended at the end of `Open`; `--source` required; options `--state` (`todo`, `in-progress`, `waiting`), `--priority` (`high`, `medium`, `low`), `--due`, `--scheduled`, `--due-note`, `--group` (group slug), `--prefix` (register still empty). An empty register takes the prefix its header reserves (``Reserved prefix: `SET` ``), else the single prefix of its archives; `--prefix` is needed only when it has neither.
- `show ID`: the action with its sub-bullets. When no register holds the ID, it is read from the archives and flagged `"archived": true`, with the archive as `register`; every write still refuses an archived action (exit code 3).
- `show ID --text [--last N]`: the same action as plain text, each piece once, to read it without the JSON (which gives every sub-bullet twice, in `details` and in `notes`). In order: the action line as written (state, ID, owner, title, group, Tasks metadata); one line `project · due <date> (<due note>) · created … · updated … · closed …`, with only the parts that exist; when the action has subtasks, `subtasks, 1 of 3 done:` then each subtask as written; the `source` sub-bullet; `history, last 3 of 12:` then the latest history entries as written, `history, 12 entries:` when all are shown, `history: none` when there is none; last, the `file:line` of the action from the Work root, followed by `(archived)` when it comes from an archive. The history is every sub-bullet but the subtasks, `source`, `due`, `created` and `updated`, so `done:` and `cancelled:` are part of it. `--last N` sets how many entries are shown (default 3, `0` for all) and is refused without `--text`. An error stays JSON. The JSON of `show ID` is unchanged.

  ```text
  - [/] **DEM-099** — Owner — Follow up with the contact ➕ 2026-10-13 📅 2026-10-20
  acme / demo · due 2026-10-20 (before the workshop) · created 2026-10-13 14:32 · updated 2026-10-16 09:05
  - source: [Minutes of 13/10](../sources/2026-10/2026-10-13-cr-demo.md)
  history, last 3 of 5:
  - 14/10: followed up by mail
  - 15/10: no answer, second mail
  - 16/10: call planned on 20/10
  brain/projects/clients/acme/missions/demo/state/actions.md:42
  ```
- `update`: only the given fields change; an empty value clears `--due`, `--scheduled` or `--group` (option absent: group unchanged). A state change files the action in its section; a closure gets `✅`/`❌` with today's date, or `--closed-on` for the date of the evidence; a reopening removes the closing date.
- `--group`: a validated slug (invalid: exit code 2). A `--title` that itself ends with a valid `#group/<slug>` tag is refused (exit code 2): pass the group through `--group`. An invalid, duplicate or mid-title tag stays in the title as is (nothing is lost on rewrite) and `check` reports it. `list --table` shows the group; the JSON of `list` and `show` carries `group`, and `title`/`raw_title` are without the tag. `sweep`, `archive`, `move`, `delete` and `history` move the line as is and keep the tag.
- `history add`: a `DD/MM: text` sub-bullet after the last history entry (`--date` for the date of the event), never among the subtasks. `history edit --index N --text T` rewrites an entry keeping its date (or `--date`) and its sub-lines. `history remove --index N` deletes it. The rank N is the `index` of `notes` in `show`, which leaves the subtasks out: adding subtasks never shifts it, and no history command reaches a subtask.
- `move --to P`: moves the action and its block to another register of the same client or internal project (the ID does not change, relative links are rewritten, a history entry records where it came from).
- `check [--register R] [--archived]`: blocking errors (malformed action line, duplicate ID across the whole client archives included, invalid date, open action with a closing date, inconsistent closure mark) and warnings (closed without a date, no source sub-bullet, invalid group slug, several `#group/` tags, tag not at the end of the title, and for subtasks: more than 10, a state other than `[ ]` or `[x]`, Tasks metadata, an `**ID**`, a subtask placed after other sub-bullets). A subtask never counts as the source sub-bullet.
- Every write accepts `--dry-run`, and the `--expect-version` (line) and `--expect-details-version` (block) locks used by the interface.
- `--brain PATH` or `BRAIN_DIR` for another brain than the default brain of Work (see [tools/README.md](../README.md)); `ACTION_NOW="YYYY-MM-DD HH:MM"` freezes the clock (tests).

## Subtasks

A subtask is one step of an action's short checklist, ticked in the tools, in tasks-web or in Obsidian:

- **Format**: `    - [ ] <text>` or `    - [x] <text>`, indented by four spaces like the other sub-bullets, optionally followed by ` ✅ YYYY-MM-DD` (Obsidian Tasks appends it when the box is ticked there: the tool reads it, writes it when it ticks, removes it when it unticks). Only the states `[ ]` and `[x]`. No ID, owner, due or scheduled date of its own: a subtask inherits its action's.
- **Place**: written directly under the action line, before every other sub-bullet, in their order. A hand-made subtask lower in the block still counts (`check` warns), and the next `subtask` write puts every subtask back under the line.
- **Rules**: one line, 15 words at most, no Tasks metadata (`📅 ⏳ ➕ ✅ ❌` or a priority), no `**ID**`; 10 subtasks at most per action. A longer text, metadata, an ID or an eleventh subtask is refused (exit code 2).
- **Commands**: `subtask add ID --text T [--position N]` (default: after the last one), `subtask toggle ID --index N [--done | --undone]` (forced state: a subtask already in it is left as is, `"unchanged": true`), `subtask edit ID --index N --text T` (state and `✅` date kept), `subtask remove ID --index N`, `subtask move ID --index N --to M` (M: its index after the move). Indices start at 0, as `index` in `show`; each command accepts `--dry-run` and `--expect-details-version`. A subtask change refreshes `updated:` and adds **no** history entry. The JSON answer carries `label`, `index` and `subtask` (the one concerned; `removed` instead for `remove`, `before` too for `edit`), the whole `subtasks` list, `subtasks_done`, `subtasks_total`, the new `details_version`, `updated_changed`, `unchanged` and `dry_run`.
- **Reading**: `show ID` adds `subtasks` (`index`, `text` without the done date, `done`, `done_on`, `""` when none), `subtasks_done` and `subtasks_total` only when the action has subtasks: the JSON of an action without any is unchanged. `list` adds `"subtasks": {"done": d, "total": t}` the same way; `list --table` and `board` write ` d/t` after the title; `show --text` prints `subtasks, d of t done:` and the subtasks as written between the dates and the source.
- **Closing**: `update --state done|cancelled` closes an action whose subtasks are still open, leaves them unticked and adds to its JSON `"warnings": ["2 subtasks of DEM-099 still open, left unticked."]` (the key is there only when it says something).
- `sweep`, `archive`, `move` and `delete` carry the subtasks with their action; a ticked subtask never makes `sweep` move anything.

## Board (`board`)

Complete, read-only view of the registers of the live projects (archived projects left out) by project: the owner's To do actions (`BRAIN_OWNER` or `owner` in `<brain>/.data/doctor.json`), the In progress and Waiting actions of everyone, sorted by ID, then the 15 most recent closures. Each line links to its line in the register. `--write [PATH]` also writes the board (default `agents/tasks-board.md`); `--watch` rewrites it when a register changes (VS Code task of the brain, when the folder opens).

## Sweep (`sweep`)

| State | Section |
|---|---|
| `[ ]` `[/]` `[w]` | `## Open` (at the end of the section) |
| `[x]` | `## Done` (most recent closure first) |
| `[-]` | `## Cancelled` (same) |

Cases covered: an action ticked in the Obsidian Tasks board (it stays in Open), a reopened action, an action filed in the wrong closed section. The sweep creates no date, state or ID: a closed action without `✅`/`❌` is moved and reported. It leaves in place, with a warning, an unknown state or an unknown or missing section.

## Archive (`archive`)

A dated `[x]` or `[-]` action, under `## Done` or `## Cancelled`, whose closure is strictly earlier than `today - --days` (30 by default), moves with its sub-bullets to `state/actions-archive-YYYY.md` (year of closure), under the section of its state, most recent closure first. Its ID stays reserved. An ID that is already archived stops that register without writing anything.

Options shared by `sweep` and `archive`: `--dry-run` (default) / `--write` / `--check` (exit code 1 if anything is to be moved), `--register PATH` (repeatable), `--days N`, `--today YYYY-MM-DD` (or `ARCHIVE_TODAY`), `--quiet`.

## Git hooks

Versioned in `tools/machine/hooks/` and installed by `tools/machine/bootstrap.sh` in every brain present; they validate and never write:

- **brain, `pre-commit`**: on an exact copy of the index (what the commit will contain, not the working folder): misfiled actions (`sweep --check`) and format of the staged registers (`check`), dead Markdown links or links to another brain if a `.md` is staged, client names of another brain (`check-no-client.py --brain … --staged`, outside the `allow` list of `.data/brain.json`); then secrets in the staged additions.
- **Work, `pre-commit`**: secrets in the staged additions.
- **Work and brain, `commit-msg`**: Conventional Commits subject (types of `kit/brain/docs/GIT.md`, lowercase, no trailing period, 100 characters at most, warning beyond 72) and no AI mention.
- **Secrets** (`check-staged-secrets.py`): credential file names and added lines that look like a key or token; values are never displayed; `secret-scan: ignore` on the line neutralizes a false positive.

## When the agent uses it

- To create, edit, complete the history of or delete an action: always this tool, never a hand edit of the register.
- To read one action: `show ID --text`, not the register; `uv run tools/brain/brain-state.py find <term>` gives the ID of the actions that mention a topic.
- When the `brain-clean` doctor reports actions to archive, or at the start of a new month: `archive --write`, without asking if the brain's conventions provide for it. After a pass over the registers: `sweep --write`.

## Guarantees

- Atomic writes; refused if the register changed between the read and the write; the archive is written before the register and restored if the register write fails. A write that would leave the register byte-identical does not rewrite it.
- Line endings and final newline preserved; `sweep` and `archive` are idempotent.
- Symbolic links and anything outside the brain are ignored.
