# Obsidian

Manual setup guide for Obsidian, to read the brains and steer the actions (`tasks.md`). The starter does not manage `.obsidian/`: the folder is ignored by Git, local to each machine, and therefore not backed up. Redo it once per machine. Never version `workspace.json` or `workspace-mobile.json`: they list the open notes.

## Vault

Open `Work/` as the **only** vault. Never open a brain (`brain/`, `brain-*/`) as a vault: the relative links to `../artifacts/` (a symlink at `Work/artifacts` when `artifactsDir` moves the artifacts folder), the template paths and the button of `tasks.md` all start from the root of `Work/`. The brains simply appear in it as folders.

## Community plugins

Settings → Community plugins → turn off Restricted mode, then install and enable:

- **Tasks** (`obsidian-tasks-plugin`): the queries of `tasks.md`;
- **Meta Bind** (`obsidian-meta-bind-plugin`): the **New action** button;
- **Templater** (`templater-obsidian`): the form behind that button, and the person page template;
- **Obsidian Git** (`obsidian-git`), optional: one brain at a time. In its settings, set the base path (`basePath`) to that of the brain (for example `brain`); suggested caution: push disabled, no pull at startup, no automatic backup after changes.

Do not enable JavaScript execution in Tasks or in Meta Bind.

## Settings to apply by hand

| Where | Setting | Value |
| --- | --- | --- |
| Files and links | Use [[Wikilinks]] | off (Markdown links, which keep the `.md` extension) |
| Files and links | New link format | Relative path to file |
| Files and links | Automatically update internal links | on (links follow a move or a rename) |
| Files and links | Excluded files | `repos/`, `agents/`, `kit/brain/seed/` (out of search and graph) |
| Files and links | Default location for new notes, optional | In the folder specified below: `brain/inbox` |
| Files and links | Default location for new attachments, optional | Same folder as current file |
| Core plugins → Templates | Template folder location | `kit/brain/templates` |
| Core plugins → Templates | Date format | `YYYY-MM-DD` |
| Templater | Template folder location | `kit/brain/templates` |
| Templater | Folder templates (enabled) | folder `brain/people` → `kit/brain/templates/_PERSON-TEMPLATE.md` |
| Meta Bind | Excluded folders | `templates` |

Adapt `brain/inbox` and `brain/people` if the brain has another name. The core plugins Templates, Bookmarks and Properties must be enabled. The form that adds an action is launched by the button of `tasks.md`, or by `Cmd+P` → `new-action` → **Templater: Insert**; do not insert it with the core Templates plugin, which would copy its code.

### Action statuses (Tasks)

Settings → Tasks → Custom statuses. The registers use five states, three of which must be added:

| Symbol | Name | Next status | Type |
| --- | --- | --- | --- |
| `/` | In Progress | `x` | IN_PROGRESS |
| `w` | Waiting | `x` | ON_HOLD |
| `-` | Cancelled | space | CANCELLED |

`[ ]` to do and `[x]` done are the base statuses of Tasks. The queries of `tasks.md` rely on the type `ON_HOLD` of the `w` status (Tasks 7 or later), not on its name: that is how they separate waiting actions from actions to do. Name it as you like, but keep the type. A brain whose `tasks.md` still filters on the status name (`status.name includes attente`, written before the English formats) needs the former setting instead: `w` named `En attente`, type `TODO`.

### Subtasks (Tasks)

An action may carry subtasks: indented checkboxes (`    - [ ] text`) directly under its line in the register, with no ID, owner or date of their own. Tasks reads every checkbox, indented or not, so the queries of `tasks.md` ignore them as stand-alone results:

- `exclude sub-items` is the second line of every query, right after the `path` filter: only top-level checkboxes (the actions) are listed, in every view including the kanban and the history;
- `show tree` closes the queries of the "In progress" box and of the per-project boxes ("By project" and "Other projects"): each action then lists its subtasks nested under it, whatever their state, without them becoming rows of their own. The "Today", "Up next", "Follow up", due date, kanban and history views stay flat.

These two instructions need a recent Tasks: the installed 8.5.0 was checked (`exclude sub-items` and the `tree` hide/show option are in its bundle); older versions are unverified. A brain created before this change gets them by copying the two lines into its own `tasks.md`.

To tick a subtask:

- in the register note (`projects/**/state/actions.md`), in live preview: click its checkbox; Obsidian appends ` ✅ YYYY-MM-DD` when it is ticked;
- from the dashboard: tick it in the nested list of an action, in the "In progress" box or in a project box (the line is rewritten in the register). The other views do not show subtasks: tick them in the register.

### CSS snippet

Copy `kit/obsidian/tasks-board.css` into `.obsidian/snippets/` (at the root of `Work/`), then Settings → Appearance → CSS snippets → enable `tasks-board`. It draws the `[/]` and `[w]` states, the kanban and the layout of `tasks.md`.

The dashboards leave archived projects out: each query that reads the registers carries `path does not include /archive/`, and the yearly `actions-archive-YYYY.md` files of live projects stay in the history view. The `path regex matches` lines carry the brain's real folder name (`^brain-name\/projects…`): a renamed brain must update its `tasks.md`.

## Bookmarks (suggestion)

Bookmarks core plugin: pin `<brain>/tasks.md` and `<brain>/inbox/inbox.md`, one group per brain if several are present.

## Graph (optional)

One color group per brain, with the query `path:<brain>/`.
