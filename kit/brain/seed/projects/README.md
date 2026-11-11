# projects/

Project pages are filed by axis: `projects/<axis>/<project>/`. The active axes are declared in [`AGENTS.md`](../../kit/brain/AGENTS.md); this starter provides `clients` and `internal`.

- [`clients/`](clients/README.md): `clients/<client>/<client>.md` is the durable index; each mission lives under `missions/<mission>/` with `state/`, `workstreams/`, `sources/YYYY-MM/`, `notes/` and `journal/`.
- `internal/<project>/<project>.md`: tooling or organization projects. [`internal/setup/setup.md`](internal/setup/setup.md) tracks the maintenance of the system itself.
- Closed projects stay in an `archive/` folder at their own level, moved there on explicit request with `uv run tools/brain/brain-state.py archive`: [`internal/archive/`](internal/archive/README.md) for internal projects, [`clients/archive/`](clients/archive/README.md) for whole clients, `clients/<client>/missions/archive/` for missions.

Create the files from [`kit/brain/templates/`](../../kit/brain/templates/README.md). The detailed structure is described in the [conventions](../../kit/brain/docs/CONVENTIONS.md).
