# projects/clients/archive/

Closed clients, each moved here whole with all its missions (`projects/clients/<client>/` becomes `archive/<client>/`) with `uv run tools/brain/brain-state.py archive clients/<client>`, only on the owner's explicit request; `unarchive` brings one back. A closed mission of a live client goes instead in `projects/clients/<client>/missions/archive/<mission>/`. An archived client leaves every command, the web interface and the dashboards; `uv run tools/brain/brain-state.py find <term> --archived` searches it. The tool rewrites the links.

[Back to clients/](../README.md)
