"""The code of the local web app, served by ../tasks-web.py (the entry point: arguments, `main()`, the restart after an update).

Modules, each importing only the ones above it:
- common: paths, the sibling tools reused (action.py, work_config.py, launch.py, preflight-push.py, check-links.py), shared
  constants, `TaskError` and the input checks;
- tools: the Tools view; markdown: folding, the renderer, front matter; brains: discovery and labels of the brains;
- settings, update, git_sync: the Settings, Update and Sync views;
- docs, priorities: documents and search, the Priorities file;
- notes, archives, store: `Store`, one brain, with the notes and archives of a brain as mixins;
- server: `Handler` and `TaskServer`.
"""
