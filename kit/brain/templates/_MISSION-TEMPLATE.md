# Mission: <Name>

> To copy to `projects/clients/<client>/missions/<mission>/<mission>.md`. Short index: current state and reading paths. Dated sources stay in `sources/`; actions and decisions are authoritative in `state/`.

- **Client:** [<Name>](../../<client>.md)
- **Status:** active | paused | done
- **Goal:** <one sentence: what "done" looks like>
- **Time tracking:** <reference confirmed by the brain owner, never guessed; optional, remove if unused>
- **Repo:** `uv run tools/repos/client-repos.py list --project <client>/<mission>` (the repositories by name, never a local path or a link into `repos/`; remove if no code)
- **Stakeholders:** [First Last](../../../../../people/first-last.md)
- **Board:** [tasks](../../../../../tasks.md)

## Summary
- <scope, deadline and stakes: 150 words at most, stable; what moves goes in Current state>

## Current state
> As of YYYY-MM-DD (<model>).
- <where the project stands, what blocks it, what comes next: 6 bullets and 150 words at most in all, with the action IDs; replaced as a whole with `uv run tools/brain/timeline.py state`, never appended to>

## Read as needed
- [Actions](state/actions.md) — authoritative ID, owner, due date and status
- [Decisions](state/decisions.md) — proposed, accepted, rejected, superseded
- [Glossary](state/glossary.md) — optional: the project's terms, acronyms and transcription errors
- [Sources of the month](sources/YYYY-MM/index.md) — one entry per substantial meeting or exchange
- [<Work topic>](workstreams/<topic>.md) — reference doc or living state of the topic, named by topic and never dated, if needed
- [<Dated note>](notes/YYYY-MM-DD-<topic>.md) — the brain owner's dated working note, if needed

## Timeline
> Internal milestones and state changes, one line each. Sources are listed in the monthly index. Only the current month stays here: as soon as it writes in a new month, the agent moves the earlier entries without asking, unchanged, into `journal/YYYY-MM.md` (brain convention) and lists the archived months below (remove that line while nothing is archived).
Previous months: [YYYY-MM](journal/YYYY-MM.md)
- YYYY-MM-DD — <milestone or state change: 40 words at most, one link to the source> (<model>)
