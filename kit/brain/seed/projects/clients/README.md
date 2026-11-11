# Clients

One folder per client: `projects/clients/<client>/`.

- `<client>.md`: durable index of the client.
- `missions/<mission>/<mission>.md`: short mission page.
- `missions/<mission>/state/`: actions and decisions.
- `missions/<mission>/workstreams/`: living reference documentation.
- `missions/<mission>/sources/YYYY-MM/`: dated sources and monthly index.
- `missions/<mission>/notes/`: dated working notes.
- `missions/<mission>/journal/`: older monthly timeline entries.
- `missions/archive/<mission>/`: closed missions, moved there on explicit request with `uv run tools/brain/brain-state.py archive`.

A closed client moves whole, with all its missions, into [`archive/<client>/`](archive/README.md).

Start from the templates [`_CLIENT-TEMPLATE.md`](../../../kit/brain/templates/_CLIENT-TEMPLATE.md) and [`_MISSION-TEMPLATE.md`](../../../kit/brain/templates/_MISSION-TEMPLATE.md).
