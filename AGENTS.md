# AGENTS.md — Work workspace

Portable agent instructions and tools for a `Work/` workspace. Reply in the user's language. Keep client names, people, mission facts, credentials, and machine-specific paths out of this repository: they belong in the private brains.

## Find the work

- `tools/` holds the reusable scripts by domain (`brain/`, `machine/`, `repos/`, `tasks-web/`); `tools/README.md` indexes the commands and `tests/` covers them. This repository ships no skill.
- `kit/brain/` holds what every brain shares, managed here and updated by `git pull starter main`: `AGENTS.md` (conventions), `docs/` (guides), `templates/` (note models), and `seed/` (files copied once into a new brain by `uv run tools/brain/new-brain.py <dir>`). Never place real client or person data in `kit/`. `kit/obsidian/` is the manual Obsidian setup guide.
- `brain/`, `brain-perso/`, and `brain-<name>/` at the Work root are the private memories: context, actions, decisions, people, own skills, and skill state. Each is a separate private Git repository and one trust boundary, declared in its `.data/brain.json`. This repository neither tracks nor references their content. The default brain, the one the tools act on when none is named, is the brain named by `"defaultBrain"` in the ignored `work-config.local.json`, else `brain/`, else the only brain at the root; `uv run tools/machine/work_config.py default-brain` prints it.
- To locate a client, project, page or register, start with `uv run tools/brain/brain-state.py map`: one line per project of every brain (`--brain NAME` for one, `--all` for the archived, `--json` for scripts).
- To answer a question from the brains, load command output, not files (`uv run tools/brain/<command>`, from the Work root):
  - where a project stands: `brain-state.py brief <project>`; late or due soon everywhere: `brain-state.py due`; what changed in a project: `brain-state.py changes --since 7d --project <project>` (rerun with `--limit N` when it prints `+N more`);
  - a topic, an identifier, a name: `brain-state.py find <term>` (`--project <project>` to stay in one project), then `action.py show <ID> --text`, `decision.py show --project <project> <number> --text` or `brain-state.py section <file>:<line>`;
  - a person and what they carry: `brain-state.py person <name>`;
  - one part of a page or of minutes: `brain-state.py section <file>` lists its headings, `section <file> <heading>` prints one (`summary` for the abstract of minutes).

  Never read a register, a project page or minutes whole. When `find` returns nothing, the brains do not hold it: say so. Archived projects are outside every command; `find <term> --archived` searches them. `action.py` and `decision.py` act on the default brain: for a hit in another one, add `--brain <brain>` before the command name.
- Before editing a brain, read `kit/brain/AGENTS.md`, then the brain's own `AGENTS.md`. For client work, start with `<brain>/projects/clients/<client>/<client>.md`, then the mission page.
- Several brains: choose the brain from its `description` (`uv run tools/brain/brain-state.py brains`) and ask when the content fits two or none. No link from one brain to another, no client name of another brain (`kit/brain/AGENTS.md`, section « Several brains »).
- `repos/` contains code repositories. Brains name a repository by its folder name, never by its local path or a link into `repos/`; `uv run tools/repos/client-repos.py list --project <project>` lists a project's repositories and which are present. Read a repository's own `AGENTS.md` before editing it. Respect client-specific gate decisions recorded in the private brain; do not re-propose an option already declined for that client.
- The artifacts folder (`artifacts/` by default, `artifactsDir` in `work-config.local.json`; `uv run tools/machine/work_config.py artifacts-dir` prints it) contains human-readable outputs and received large files, each folder with a provenance `README.md`. Its contents are local and are not backed up by this repository. When `artifactsDir` points outside Work (a synced cloud folder), `artifacts/` is a symlink to it, so links to `artifacts/…` keep working; `bootstrap.sh` creates the link and copies the folder's `README.md` from `kit/artifacts/README.md`.
- `agents/` is scratch: an agent removes only what it created in the same session, the owner clears the rest. Promote durable information to the right brain, durable code to a repository, and durable outputs to the artifacts folder.
- Obsidian opens `Work/` as the only vault. `.obsidian/` is ignored and set by hand on each machine (`kit/obsidian/README.md`).

## Skills and configuration

- Own skills live in `<brain>/skills/<name>/` (a `.install-as-copy` marker installs a copy instead of a link). Third-party skills are listed in `<brain>/.data/work-config.json`; install one with `npx skills add <source>`, then record it with `uv run tools/machine/work_config.py adopt [--brain <name>]` (the default brain unless named).
- Configuration layers, the last one winning: `work-config.example.json`, each brain's `.data/work-config.json`, then the ignored `work-config.local.json` (template: `work-config.local.example.json`) for choices that concern one machine (for example disabling a skill, `"defaultBrain": "brain-<name>"` or `"artifactsDir": "<path>"`, which no other layer accepts). `uv run tools/machine/work_config.py check` validates them.
- Codex discovers skills in `.agents/skills/`, Claude in `.claude/skills/`. Both are generated and ignored, like `skills-lock.json` and `.work-state.json`: never edit them, run `tools/machine/update.sh`. Do not create `.codex/skills/` or install skills globally.

## Keep repository boundaries

- Reusable scripts belong in `tools/`. Client-specific data, brand kits, mappings, and cursor files belong in the `.data/` of the brain they concern, or in the appropriate local artifact folder.
- Markdown files in `Work/` never cite documents located outside `Work/` (downloads, synced cloud folders, mail attachments): no local path or file name. Web links (`https://…`) may stay for traceability. Copy a document that must stay cited into the artifacts folder (`artifacts/` by default, `artifactsDir` in `work-config.local.json`; `uv run tools/machine/work_config.py artifacts-dir` prints it) with its provenance `README.md` and cite that copy; links to a file of that folder keep the form `artifacts/…`, since the folder stays reachable at `Work/artifacts`, possibly as a symlink; otherwise describe its provenance in words. Input folders that skills read outside `Work/` belong in the default brain's `.data/local-paths.json`, not in Markdown.
- Client repository URLs belong only in the default brain's private `.data/client-repos.json`. Use `tools/repos/client-repos.py` to list, check, or clone them; never copy those URLs into this repository.
- Tests, fixtures, examples and docstrings use fictitious names only (`acme`, `globex`, `initech`, `brain-acme`…): never the name of the owner's employer, a client, a person or a real project.
- `tools/machine/check-no-client.sh` scans for the names already listed in the private brains (clients, people, and the employer name); the Work pre-commit hook runs it on the staged files. It does not certify that a file is safe to publish; review the files and staged diff yourself.

## Hard rules

- Write every change to this workspace in English — code, comments, messages, documentation, templates, skills and commit messages — even when the conversation is in another language. Reply to the user in their language. A brain may keep content written in its owner's language (notes, minutes, people pages): edit that content in the language it is written in.
- Never commit or push without a separate explicit request for each action. Stage only paths touched for that action, inspect the staged diff, and use Conventional Commits without AI attribution. The hooks installed by `bootstrap.sh` refuse staged secrets, private names in Work, non-conforming messages, and pushes with the wrong identity, a force push or a remote branch deletion; never bypass them (`--no-verify`). In Claude Code, `.claude/settings.json` also refuses direct `python`, deletions in the artifacts folder, hook bypasses and writes into an artifacts/ folder not yet linked to the configured one before a command runs.
- Never delete anything in the artifacts folder, even a file you produced. In `agents/`, delete only what you created yourself in the same session (tests, fixtures, intermediate files); never the files of an earlier session, of another agent or of the owner. The only other move allowed is into an `archive/` folder inside them (for example `agents/archive/`, or `archive/` in the artifacts folder); the owner removes the rest.
- Do not read, print, or copy the contents of `.env`, private keys, or credentials. `tools/.env` is ignored; `tools/.env.example` contains names only.
- Do not edit home-directory configuration, SSH files, cloud configuration, or keychains without explicit user confirmation.
- Never open or interact with an Internet site to perform an operation on the user's behalf. For online changes, prepare the content or instructions and let the user apply them.
- Before any remote write or a first clone, read `tools/machine/GIT-IDENTITY.md`: how the Git author and SSH key are chosen per trust boundary, and how to verify them.
- Scripts that write to an external service require an explicit request for that specific operation.

## Workflows

- Run Python scripts with `uv run <script>`; do not invoke `python` or `python3` directly.
- `tools/machine/install.sh` is the one-command setup after cloning `Work`: it clones `brain/` or creates a blank one from `kit/brain/seed/` (and optionally `brain-perso/`), then runs `bootstrap.sh` (local directories, the artifacts folder included, Git hooks in Work and in every brain, skills, link checks). It never restores local artifacts.
- Another brain is created with `uv run tools/brain/new-brain.py brain-<name> --scope … --description …`, or cloned by hand with the identity of its own boundary; run `bootstrap.sh` again to install its hooks.
- `tools/machine/update.sh` regenerates the skill installs and links from the configuration and reports the Git state of Work and of each brain. It does not pull, commit, or push.
- At the start of every conversation, unless the session context already holds its result (the Claude Code SessionStart hook prints it), run `uv run tools/machine/setup.py status`. While settings are missing, ask the user for each one before any other work, one question at a time, in their language, saying its default; write each answer with `uv run tools/machine/setup.py set <key> <value>`, or `uv run tools/machine/setup.py default <key>` when the user says to ignore or skip it (an item without a default cannot be skipped), then continue with the request. Mention the owner actions it lists once, without blocking.
- `uv run tools/machine/doctor.py` (read-only, no network) reports what is missing or out of date on this machine, including a configuration changed since the last `update.sh` and a brain whose remote or e-mail leaves its declared boundary. `tools/machine/check-links.sh` checks the skill links and the Markdown links of every brain; run it after moving files.
- After code work, update the relevant mission page and action register in the right brain, leaving a short dated entry and outstanding work. Do not copy code into memory.
- Write to a brain only what is worth versioning: a change, a decision, a delivery, a milestone, or a result someone will look for later. A check, a test, or a rerun that changes nothing gets no timeline entry; report it in the reply instead.
