# Setup and maintenance

How Work is laid out, how to set it up on a machine, move it to another one, update it and check it. Back to the [README](../README.md).

## Layout

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
| `brain/`, `brain-perso/`, `brain-<name>/` | Private memories, one trust boundary each (see [the default brain](BRAINS.md#brains-and-trust-boundaries))       | One separate private repository each |
| `repos/`                                  | Code clones                                                                   | Each clone has its own repository    |
| `artifacts/`                              | Human-readable outputs and large inputs                                       | Local files, ignored                 |
| `agents/`                                 | Scratch; an agent removes only its own session's files                        | Local files, ignored                 |

Local to each machine and ignored: `.agents/` and `.claude/skills/` (skills exposed to the agents), `.obsidian/`, `work-config.local.json`, the generated `skills-lock.json` and `.work-state.json`, and `tools/.env`.

The rule README files in `repos/`, `artifacts/`, and `agents/` are tracked. Their working contents are ignored. `artifacts/` is an ordinary local directory: there is no cloud link or automatic restore on a new machine.

## Set up a new machine

`tools/machine/install.sh` ([Quick start](../README.md#quick-start) of the README) prepares the brains and runs `bootstrap.sh`. `--brain-dir brain-<name>` puts the brain in that folder instead of `brain/` and records it as the default brain, `--brain-perso <url|new>` adds the optional personal brain, `--no-bootstrap` stops before `bootstrap.sh`, and `--help` lists all options. The `origin` remote pointing to this public repository (`alpyt42/Work`, formerly Work-Starter) is renamed `starter`, so you can add your own. It is public and read-only for everyone but its owner: clone, pull, or fork it, but changes are never pushed back. The brain conventions (`kit/brain/AGENTS.md`, `docs/`, `templates/`) live in this repository; a brain is a private repository that holds only your own data and points to them. Or do it by hand:

1. Configure Git and SSH identities yourself, outside this repository: one `~/.gitconfig-<boundary>` per trust boundary, included from `~/.gitconfig` by folder and by remote URL (template: `tools/machine/gitconfig.example`), and one `Host` block per single-account host in `~/.ssh/config`. Check a folder with `git -C <path> config --show-origin --get-regexp '^(user|core\.sshcommand)'`.
2. Clone this repository as `Work/` (or copy it with a fresh history) using the Git identity meant for your personal tooling.
3. Get your private brain: create a blank one with `uv run tools/brain/new-brain.py brain` (from `kit/brain/seed/`) and give it a private remote yourself, or clone an existing one into `brain/` (bootstrap does it when `BRAIN_REMOTE=<private-brain-git-url>` is set). Other brains are created the same way (see [Brains](BRAINS.md#brains-and-trust-boundaries)).
4. Run `./tools/machine/bootstrap.sh` from `Work/` (with `BRAIN_REMOTE` set when `brain/` is not cloned yet), then check that each brain is the intended private repository and that `./tools/machine/check-links.sh` passes.
5. Clone each other brain listed under `brains` in the default brain's `.data/local-paths.json` yourself, with the identity of its own boundary; bootstrap clones only `brain/`, and only when no brain exists yet. Run `bootstrap.sh` again to install the Git hooks in a brain cloned by hand (`new-brain.py` installs them in a brain it creates).
6. Adjust the input folders in the default brain's `.data/local-paths.json` (relative to the home directory) if this machine stores transcripts or recordings elsewhere.
7. Restore `artifacts/` from your own backup if you need past deliverables.
8. Run `uv run tools/machine/doctor.py`: it reports, read-only and without network access, missing commands and brains, repositories without upstream or with unpushed commits, brains whose remote or e-mail leaves their declared boundary, a skill configuration changed since the last update, skills not adopted or not installed, broken skill links, missing input folders, unreadable `.data/*.json` states, and the number of files in the unbacked `artifacts/`.

`bootstrap.sh` needs Git and `uv`; `uv` runs the Python tools. Node.js (`npx`) is needed only when third-party skills are enabled. The brain remotes are intentionally not stored in this repository. Each brain's `.data/` is versioned with that brain. `artifacts/` starts empty on a new machine.

On Windows:

- Run the scripts in Git Bash, installed with [Git for Windows](https://gitforwindows.org/), from the `Work/` root.
- Install `uv`, and Node.js LTS when third-party skills are enabled; open a new terminal afterwards so that the `PATH` includes them.
- Turn on Developer Mode (Settings > System > For developers): the skills and a relocated artifacts folder are symbolic links, which Windows otherwise reserves to administrators. `bootstrap.sh` stops before any change when it cannot create one, and `doctor.py` reports a skill copied where a link was expected.
- In `~/.gitconfig`, write the folder rules as `gitdir/i:` (Windows paths are case-insensitive; see `tools/machine/gitconfig.example`).
- Line endings need no setting: the `.gitattributes` of Work and of every brain created from `kit/brain/seed/` check text files out with LF, whatever `core.autocrlf` says (bash and the Git hooks fail on CRLF). A brain created before has none: copy `kit/brain/seed/.gitattributes` into it.

## Another computer

1. On the first machine, commit and push each brain yourself (a new skill, a changed `.data/work-config.json`).
2. On the other machine, clone Work and every brain as in [Set up a new machine](SETUP.md#set-up-a-new-machine), or `git pull` in each existing one.
3. Run `tools/machine/update.sh`: it validates the configuration, rewrites the lock, installs the third-party skills, refreshes the links and copies, checks the links, records the resolved configuration, and reports the Git state of Work and of each brain. It never pulls, commits, or pushes.

`uv run tools/machine/doctor.py` warns when the resolved configuration changed since the last `update.sh`, so a pulled brain that adds or removes a skill is never silent. `artifacts/` is not synchronised.

## Update the starter

Work updates by releases, not by pulling the tip of `main`. Every push to `main` of the public repository runs `.github/workflows/release.yml`: it tests on Linux, then publishes the next version, derived from the Conventional Commits since the last release (details in [`tools/machine/README.md`](../tools/machine/README.md#publishing-a-release)). On your machine, in `Work/`:

```bash
uv run tools/machine/work.py update --check   # is a newer release available, and what would change
uv run tools/machine/work.py update --apply --to vX.Y.Z   # fast-forward to that release, then run update.sh
```

The Update button of the Actions app does the same. The shared conventions, guides, templates, and tools follow; your brains, your configuration, and your local files are not touched. An update is blocked, with its reasons, by local commits, by modified files the release also changes, by a new major version, by a detached HEAD or by a missing upstream.

## Checks

- `./tools/machine/check-links.sh` after moving files: skill configuration, links and copies, then the Markdown links of every brain (`uv run tools/brain/check-links.py` checks one brain; a link into another brain fails).
- `uv run tools/machine/doctor.py` for the state of the machine (see step 8 above).
- `tools/machine/check-no-client.sh [--staged|--worktree]` is an optional manual scan: it compares publishable file names and text of this repository with known client and person names from the default brain. `uv run tools/machine/check-no-client.py --brain <dir> --staged|--worktree` scans one brain against the client names of the other brains; the brain's pre-commit hook runs it. Neither detects all confidential information: review the complete diff and staged file list before committing.
- Git hooks installed by `bootstrap.sh`: in Work, staged secrets and commit messages (Conventional Commits, no AI attribution); in each brain, malformed or misplaced actions, dead and cross-brain links, client names of other brains, staged secrets, and the same commit-message check.
- Tests: `uv run --with pytest --with markdown-it-py --with tzdata pytest tests/` (see [`tests/README.md`](../tests/README.md)).

No commit or push is performed by setup or update scripts.
