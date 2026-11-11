# Code repositories to clone

The private catalogue `.data/client-repos.json` versions **only the local paths, the `origin` URLs and the projects** of the code repositories, client and internal ones alike. It pins neither a branch nor a commit. Repository URLs never go into a personal or public tooling repository: only here, in the private brain.

Format (schema 2): `{"schema_version": 2, "repositories": [{"path": "repos/<group>/<repo>", "url": "<git-url>", "project": "<project>"}]}`. `project` is optional and names the brain project the repository belongs to, as `brain-state.py brief` accepts it (`<client>/<mission>`, or the folder name of an internal project). The actual state of the catalogue lives exclusively in `.data/client-repos.json`.

The pages of the brain name a repository by its folder name, never by its local path or a link into `repos/`: the catalogue answers which repositories a project uses and which are present on this machine, and `brain-state.py brief` sums it up in one line. If the workspace provides `tools/repos/client-repos.py`, it reads this catalogue:

```bash
uv run tools/repos/client-repos.py list --project <project>      # present or missing, path, project
uv run tools/repos/client-repos.py status [--project <project>]  # branch, changes, ahead/behind, last commit; Git roots missing from the catalogue
uv run tools/repos/client-repos.py list                          # every path and URL
uv run tools/repos/client-repos.py check                         # origin + applied author and key, no network
uv run tools/repos/client-repos.py clone <client>                # plain git clone, identity inherited from ~/.gitconfig
```

Before the first clone for a client, register its public key and check the server's host key (see [`GIT.md`](GIT.md)). If a repository changes URL, check the new remote with the client, fix the catalogue, then run `check` again.
