<p align="center">
  <img src="tools/tasks-web/static/icon.png" alt="Work app icon" width="96">
</p>

<h1 align="center">Work</h1>

<p align="center">A workspace where your coding agent remembers each client's context and never mixes one with another.</p>

<p align="center">
  <a href="https://github.com/alpyt42/Work/releases"><img src="https://img.shields.io/github/v/release/alpyt42/Work" alt="Latest release"></a>
  <a href="https://github.com/alpyt42/Work/actions/workflows/release.yml"><img src="https://github.com/alpyt42/Work/actions/workflows/release.yml/badge.svg" alt="Release workflow status"></a>
</p>

## The problem

- Every new Claude Code or Codex session starts without the context of the last one.
- Loading whole project files fills the agent's context window.
- With several clients on one machine, one client's data can end up in another's repository.

Work is a portable `Work/` workspace that fixes this. Memory lives in private Markdown repositories called brains, one per trust boundary. Agents read them through small commands that return only the part a question needs. Git hooks keep the boundaries intact. A local app lets you read and edit the same files without an agent. The repository holds the tools, the shared conventions and the checks. It holds no client data.

## Features

- **Private Markdown brains.** Each brain is its own Git repository and its own trust boundary, declared in `.data/brain.json` with the remote and e-mail it must use. Personal, employer and client data never share a repository. The repository ships no skill: skills live in the brains.
- **Context on demand.** `brain-state.py` loads output, not files: `brief` for where a project stands, `find` for a term or an identifier, `section` for one heading of a page, `person` for someone and what they carry, `due` for late and upcoming actions, `changes` for what moved since a date. Agents never read a register or a project page whole.
- **Action and decision registers.** `action.py` and `decision.py` write the registers, with length caps (35 words for a history entry, 40 for a timeline entry, 70 for a decision field). A commitment becomes an action only when four tests hold; otherwise it stays in the minutes or message where it was said.
- **Project archiving.** `brain-state.py archive` moves a finished mission, project or client into an `archive/` folder, rewrites the links, and refuses while an action is still open. An archived project leaves every command and every view. `unarchive` is the exact inverse.
- **A local Actions app.** `tasks-web.py` serves a browser interface on `127.0.0.1` with the views Today, Actions, Board, Timeline, Docs, Archives, Tools, Sync, Settings, and one search across actions and documents. A selector switches between brains. Sync saves and sends a brain's changed notes through its own Git hooks. It installs as an app on macOS, Windows and Linux (`install-app.py`).
- **Guardrails.** Git hooks refuse staged secrets, the names of clients and people known to the other brains, malformed commit messages, dead or cross-brain links, and pushes with the wrong identity, a force push or a remote branch deletion. A Claude Code hook refuses direct `python`, deletions in the artifacts folder, hook bypasses and writes into an `artifacts/` folder not yet linked to the configured one. `preflight-push.py` runs before every push.
- **Obsidian compatible.** Open `Work/` as the vault. Each brain's `tasks.md` shows the registers as Tasks queries and a kanban, with a form to add an action.
- **Releases.** Every push to `main` is tested on Linux and released automatically from its Conventional Commits. Machines update to a release only, never to the tip of `main`, and an update never touches the brains.

## How it works

```
Work/
├── tools/          reusable scripts: brain/, machine/, repos/, tasks-web/
├── kit/            conventions, guides, templates and seed shared by every brain
├── brain/          private memory, its own Git repository
├── brain-<name>/   one more brain per trust boundary, each its own repository
├── repos/          code clones, each with its own repository
├── artifacts/      human-readable outputs and large inputs, local only
└── agents/         scratch space for agents
```

1. The agent gets a question about a client or a project.
2. It runs a context command (`brain-state.py brief`, `find`, `section`, `person`).
3. Only the part it needs enters the context window.

## Quick start

Configure Git and SSH identities first (see [`tools/machine/GIT-IDENTITY.md`](tools/machine/GIT-IDENTITY.md)), then:

```bash
git clone https://github.com/alpyt42/Work.git ~/Work
~/Work/tools/machine/install.sh --brain <private-brain-git-url> [--brain-perso <git-url|new>]
```

Without `--brain`, a blank brain is created locally from `kit/brain/seed/`. The script never touches home configuration, never commits or pushes, and can be rerun safely. Details are under [Set up a new machine](#set-up-a-new-machine).

## Reference

### Layout

| Path                                      | Role                                                                          | Git ownership                        |
| ----------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------ |
| `AGENTS.md`, `CLAUDE.md`                  | Map of the workspace for agents                                               | This repository                      |
| `tools/`                                  | Reusable scripts by domain (`brain/`, `machine/`, `repos/`, `tasks-web/`); setup, hooks and checks in `tools/machine/` | This repository |
| `kit/brain/`                              | Conventions, guides, templates and seed shared by every brain                 | This repository                      |
| `kit/obsidian/`                           | Manual Obsidian setup guide and task-board CSS                                | This repository                      |
| `tests/`                                  | Tests of the tools                                                            | This repository                      |
| `work-config.example.json`                | Public defaults of the skill configuration                                    | This repository                      |
| `work-config.local.example.json`          | Template of the ignored `work-config.local.json`, with every machine-only key (`defaultBrain`, `artifactsDir`, disabled skills) | This repository |
| `.claude/`                                | Claude Code settings (`settings.json`, empty); `skills/` is generated         | This repository (`skills/` ignored)  |
| `brain/`, `brain-perso/`, `brain-<name>/` | Private memories, one trust boundary each (see the default brain below)       | One separate private repository each |
| `repos/`                                  | Code clones                                                                   | Each clone has its own repository    |
| `artifacts/`                              | Human-readable outputs and large inputs                                       | Local files, ignored                 |
| `agents/`                                 | Scratch; an agent removes only its own session's files                        | Local files, ignored                 |

Local to each machine and ignored: `.agents/` and `.claude/skills/` (skills exposed to the agents), `.obsidian/`, `work-config.local.json`, the generated `skills-lock.json` and `.work-state.json`, and `tools/.env`.

The rule README files in `repos/`, `artifacts/`, and `agents/` are tracked. Their working contents are ignored. `artifacts/` is an ordinary local directory: there is no cloud link or automatic restore on a new machine.

### Set up a new machine

`tools/machine/install.sh` (Quick start above) prepares the brains and runs `bootstrap.sh`. `--brain-perso <url|new>` adds the optional personal brain, `--no-bootstrap` stops before `bootstrap.sh`, and `--help` lists all options. The `origin` remote pointing to this public repository (`alpyt42/Work`, formerly Work-Starter) is renamed `starter`, so you can add your own. It is public and read-only for everyone but its owner: clone, pull, or fork it, but changes are never pushed back. The brain conventions (`kit/brain/AGENTS.md`, `docs/`, `templates/`) live in this repository; a brain is a private repository that holds only your own data and points to them. Or do it by hand:

1. Configure Git and SSH identities yourself, outside this repository: one `~/.gitconfig-<boundary>` per trust boundary, included from `~/.gitconfig` by folder and by remote URL (template: `tools/machine/gitconfig.example`), and one `Host` block per single-account host in `~/.ssh/config`. Check a folder with `git -C <path> config --show-origin --get-regexp '^(user|core\.sshcommand)'`.
2. Clone this repository as `Work/` (or copy it with a fresh history) using the Git identity meant for your personal tooling.
3. Get your private brain: create a blank one with `uv run tools/brain/new-brain.py brain` (from `kit/brain/seed/`) and give it a private remote yourself, or clone an existing one into `brain/` (bootstrap does it when `BRAIN_REMOTE=<private-brain-git-url>` is set). Other brains are created the same way (see [Brains](#brains-and-trust-boundaries)).
4. Run `./tools/machine/bootstrap.sh` from `Work/` (with `BRAIN_REMOTE` set when `brain/` is not cloned yet), then check that each brain is the intended private repository and that `./tools/machine/check-links.sh` passes.
5. Clone each other brain listed under `brains` in the default brain's `.data/local-paths.json` yourself, with the identity of its own boundary; bootstrap clones only `brain/`, and only when no brain exists yet. Run `bootstrap.sh` again to install the Git hooks in it.
6. Adjust the input folders in the default brain's `.data/local-paths.json` (relative to the home directory) if this machine stores transcripts or recordings elsewhere.
7. Restore `artifacts/` from your own backup if you need past deliverables.
8. Run `uv run tools/machine/doctor.py`: it reports, read-only and without network access, missing commands and brains, repositories without upstream or with unpushed commits, brains whose remote or e-mail leaves their declared boundary, a skill configuration changed since the last update, skills not adopted or not installed, broken skill links, missing input folders, unreadable `.data/*.json` states, and the number of files in the unbacked `artifacts/`.

`bootstrap.sh` needs Git and `uv`; `uv` runs the Python tools. Node.js (`npx`) is needed only when third-party skills are enabled. The brain remotes are intentionally not stored in this repository. Each brain's `.data/` is versioned with that brain. `artifacts/` starts empty on a new machine.

### Brains and trust boundaries

A brain is a private Git repository at the Work root named `brain` or `brain-<name>` (for example `brain-perso`). The default brain, the one the tools act on when none is named, is the brain named by `"defaultBrain"` in the ignored `work-config.local.json`, else `brain/`, else the only brain at the root (`uv run tools/machine/work_config.py default-brain` prints it). Each one is a trust boundary: personal data goes in a brain pushed to a personal Git account, employer or client data in a brain pushed to the employer's Git. Create one from the seed and declare its boundary at once:

```bash
uv run tools/brain/new-brain.py brain-perso \
  --scope personal \
  --description "Personal meetings and career topics; no employer or client content" \
  --remote 'git@github.com:<personal-account>/*' \
  --email '<personal-address>'
```

The new folder is a copy of `kit/brain/seed/` with a fresh Git repository on `main`, no commit and no remote; an existing folder is never touched, and `--no-git` skips `git init`. Add a private remote yourself before the first push. The boundary lives in the brain's `.data/brain.json`:

- `scope` and `description`: what the brain holds and must never hold. Agents read them (`uv run tools/brain/brain-state.py brains`) to choose the brain where new content goes, and ask when two brains fit or none does.
- `remote` and `email`: `fnmatch` patterns that the clone's `origin` URL and effective `user.email` must match, checked by `doctor.py`.
- `allow`: client names of another brain that may appear in this one.

Where data goes: each brain holds its own projects, people, actions, sources and skill states (`.data/`); the shared settings (expected `brains`, input folders) live in the default brain's `.data/local-paths.json`. Rules: no Markdown link from one brain to another and no client name of another brain in a brain's paths or content. `uv run tools/brain/check-links.py`, `check-no-client.py --brain` and the brain's pre-commit hook enforce both. Conventions: [`kit/brain/AGENTS.md`](kit/brain/AGENTS.md).

### Skills

This repository ships no skill. Each brain holds its own:

- **Own skills** live in `<brain>/skills/<name>/` (`SKILL.md`, optional `scripts/`, `references/`, `assets/`). A skill folder containing an empty `.install-as-copy` file is installed as a copy; the others are linked. A private skill sits in the private brain whose data it touches, and its state goes in that brain's `.data/`.
- **Third-party skills**: install one with `npx skills add <source>`, then run `uv run tools/machine/work_config.py adopt [--brain <name>]`. It records the skill in that brain's `.data/work-config.json` (the default brain unless named), so that it follows the brain to your other machines. Commit and push the brain yourself.
- **Disable a skill on one machine** in the ignored `work-config.local.json` (template: `work-config.local.example.json`; `uv run tools/machine/setup.py` writes its keys for you): `{"version": 1, "skills": {"disabled": ["<skill>"]}}`, then run `tools/machine/update.sh`. The local file may also override a third-party entry.

Configuration layers, the last one winning: `work-config.example.json` (public defaults), each brain's `.data/work-config.json` (the default brain first, then the others by name), `work-config.local.json` (the only layer that accepts `"defaultBrain"`). Disabled names are the union of all layers; the same own-skill name in two brains, or a name both own and third-party, is an error. `work_config.py` also offers `check`, `list-brains`, `default-brain`, `list-own`, `list-third-party`, `list-catalog`, `lock`, `stamp`, and `status`. Codex discovers skills in `.agents/skills/` and Claude in `.claude/skills/`; both are generated by `tools/machine/update.sh` (links to brain skills, copies for `.install-as-copy`, third-party skills installed from the generated `skills-lock.json`) and never edited by hand.

Client-specific configuration belongs in the `.data/` of the brain it concerns. Credentials never go in a brain or in this repository: use the environment or an ignored `.env`.

### Another computer

1. On the first machine, commit and push each brain yourself (a new skill, a changed `.data/work-config.json`).
2. On the other machine, clone Work and every brain as in [Set up a new machine](#set-up-a-new-machine), or `git pull` in each existing one.
3. Run `tools/machine/update.sh`: it validates the configuration, rewrites the lock, installs the third-party skills, refreshes the links and copies, checks the links, records the resolved configuration, and reports the Git state of Work and of each brain. It never pulls, commits, or pushes.

`uv run tools/machine/doctor.py` warns when the resolved configuration changed since the last `update.sh`, so a pulled brain that adds or removes a skill is never silent. `artifacts/` is not synchronised.

### Update the starter

Work updates by releases, not by pulling the tip of `main`. Every push to `main` of the public repository runs `.github/workflows/release.yml`: it tests on Linux, then publishes the next version, derived from the Conventional Commits since the last release (details in [`tools/machine/README.md`](tools/machine/README.md#publishing-a-release)). On your machine, in `Work/`:

```bash
uv run tools/machine/work.py update --check   # is a newer release available, and what would change
uv run tools/machine/work.py update --apply --to vX.Y.Z   # fast-forward to that release, then run update.sh
```

The Update button of the Actions app does the same. The shared conventions, guides, templates, and tools follow; your brains, your configuration, and your local files are not touched. An update is blocked, with its reasons, by local commits, by modified files the release also changes, by a new major version, by a detached HEAD or by a missing upstream.

### Repositories

Client clone URLs are versioned in the private `.data/client-repos.json` of the default brain. Use `uv run tools/repos/client-repos.py list` to see them, `check` to compare existing `origin` URLs and show each clone's effective author and key, and `clone <client>` to recreate a client's clones. `clone` is a plain `git clone`: author and key come from the home rules of step 1, and the command refuses to clone when no rule gives an author for the destination. `--identity` and `--author-*` remain available for a one-off override written to the clone. This repository stores only the generic tool.

### Obsidian

Open `Work/` as the only Obsidian vault; the brains appear as folders inside it. The starter does not manage `.obsidian/`: it is ignored by Git and set by hand once per machine, following [`kit/obsidian/README.md`](kit/obsidian/README.md) (community plugins Tasks, Meta Bind, Templater and optionally Obsidian Git, the link and template settings, the task statuses, and the `tasks-board` CSS snippet in [`kit/obsidian/tasks-board.css`](kit/obsidian/tasks-board.css)).

Each brain's `tasks.md` combines the daily dashboard, project lists and kanban columns as Obsidian **Tasks** queries over the action registers. To add an action, click **New action** at the top of `tasks.md`; the Meta Bind button runs the Templater form, which writes to the chosen register with an ID, status, optional priority and a validated Tasks due date. The keyboard alternative is to search for `new-action` in the command palette and select **Templater: Insert**.

Outside Obsidian, `uv run tools/brain/action.py board` prints a complete project view of the same registers, sorted by state then action ID; the daily planning dashboard remains in Obsidian (`--write` saves the project view to `agents/tasks-board.md` for the VS Code Markdown preview, each line linking to its register line; `--write --watch` keeps it up to date, and the VS Code task « Tasks board (live) » in a brain's `.vscode/tasks.json` starts it when the folder opens, once automatic tasks are allowed). In VS Code, the Todo Tree extension lists in-progress `[/]`, waiting `[w]`, and the owner's to-do `[ ]` actions live. Its settings live in the private brain's `.vscode/settings.json` because the regex names the owner; to open `Work/` instead, copy them to the ignored `Work/.vscode/settings.json` and add `"todo-tree.ripgrep.ripgrepArgs": "--max-columns=1000 --no-ignore"` (this repository's `.gitignore` hides the brains from ripgrep). Todo Tree may not find VS Code's bundled ripgrep: install it (`brew install ripgrep`) and set `todo-tree.ripgrep.ripgrep` to its path in the VS Code user settings.

Closed actions older than 30 days move to `state/actions-archive-YYYY.md` with `uv run tools/brain/action.py archive` (dry-run) then `--write`; agents run it without asking when the doctor flags them or at the start of a month. See [tools/brain/action.md](tools/brain/action.md).

### The Actions app

Run `uv run tools/tasks-web/tasks-web.py` and open `http://127.0.0.1:8765/`: a sidebar with the views Today, Actions, Board, Timeline, Docs, Archives, Tools, Sync and Settings, a search field in the header that searches the actions and the documents, the **New action** and **New note** buttons, and a selector at the top left that switches between the brains of the Work without a restart. The Sync view shows one card per brain and, after a confirmation, saves its changed notes and sends them to the brain's own online copy, through the brain's Git hooks. An **Update** button appears when a newer release exists. `uv run tools/tasks-web/install-app.py` installs an **Actions Brain** entry (macOS app, Windows Start Menu shortcut, Linux applications menu); on macOS, `./tools/tasks-web/build-dock-app.sh` runs the same installer. Both routes read and edit the same Markdown files; details are in [the local task manager guide](tools/tasks-web/README.md). The server binds only to `127.0.0.1` and publishes nothing by itself: a brain leaves this computer only when you click **Save and send** or **Send** in the Sync view.

### Checks

- `./tools/machine/check-links.sh` after moving files: skill configuration, links and copies, then the Markdown links of every brain (`uv run tools/brain/check-links.py` checks one brain; a link into another brain fails).
- `uv run tools/machine/doctor.py` for the state of the machine (see step 8 above).
- `tools/machine/check-no-client.sh [--staged|--worktree]` is an optional manual scan: it compares publishable file names and text of this repository with known client and person names from the default brain. `uv run tools/machine/check-no-client.py --brain <dir> --staged|--worktree` scans one brain against the client names of the other brains; the brain's pre-commit hook runs it. Neither detects all confidential information: review the complete diff and staged file list before committing.
- Git hooks installed by `bootstrap.sh`: in Work, staged secrets and commit messages (Conventional Commits, no AI attribution); in each brain, malformed or misplaced actions, dead and cross-brain links, client names of other brains, staged secrets, and the same commit-message check.
- Tests: `uv run --with pytest --with markdown-it-py pytest tests/` (see [`tests/README.md`](tests/README.md)).

No commit or push is performed by setup or update scripts.
