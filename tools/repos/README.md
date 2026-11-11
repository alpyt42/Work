# tools/repos

`client-repos.py` reads the private catalog `.data/client-repos.json` of the default brain and answers "which
repositories does a project use, and which are present on this machine". Catalog URLs never leave the brain.

## Catalog schema

```json
{"schema_version": 2, "repositories": [{"path": "repos/<group>/<name>", "url": "<ssh url>", "project": "<project>"}]}
```

- `path`: exactly `repos/<group>/<name>`; each folder starts with a letter or digit and contains letters (any case),
  digits, `.`, `_`, `-`. No `..`, no absolute path, no symlink escape.
- `project` (version 2, optional): the brain project the repository belongs to, as `brain-state.py brief` accepts it
  (`acme/demo` for a client mission, `notes` for an internal project). Plain text, at most one `/`, no `..`.
  Internal (non-client) repositories are allowed. Version 1 (`path` and `url` only) stays readable.

## Commands

All local except `clone`; run with `uv run tools/repos/client-repos.py`.

- `list [selector] [--project P] [--present | --missing] [--json]`: without flags, `path  url` as before. With a
  flag, one line per entry: `present`/`missing`, path, project (or `-`). `--project` matches exactly; entries
  without `project` never match. `--json` adds `url`, `project`, `present`.
- `status [selector] [--project P] [--json]`: for each present repository, branch, number of changed files,
  ahead/behind of the local upstream ref (omitted without upstream) and last commit date; then Git roots under
  `repos/` that no entry names (omitted with `--project`). Git calls time out after 10 s; a broken repository is
  reported as `ERROR`, never fatal.
- `check`, `clone`: see the script header.

## Row for `tools/README.md`

| `uv run tools/repos/client-repos.py status [--project P] [--json]` | Local state of the repositories present (branch, changes, ahead/behind, last commit) and Git roots under `repos/` missing from the catalog; `list` also takes `--project`, `--present`, `--missing`, `--json` | `tools/repos/README.md` |
