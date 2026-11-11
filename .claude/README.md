# .claude/

Claude Code configuration of the `Work/` project.

- `settings.json` — shared settings tracked by Git. It runs `tools/machine/hooks/claude-bash-guard.py` before every Bash command (refuses direct `python`, deletions or moves out of `artifacts/`, and Git hook bypasses); the hook needs `uv`. It also runs `tools/machine/hooks/claude-session-start.py` at session start (SessionStart): under 150 words on the default brain, the brains found, uncommitted paths and unpushed commits of Work and each brain (local Git only, counts only, never fails). Personal settings go in `settings.local.json`, which is ignored.
- `agents/` — Claude Code subagents tracked by Git, generic only (no client, person or brand name). `deck-inspector.md` inspects a rendered deck slide by slide and returns a short defect list, so the slide images stay out of the main context; the `brand-deck` skill delegates to it. Claude-only: a skill that uses a subagent must still work without it.
- `skills/` — entirely generated and ignored by Git: links to the skills of the brains (`<brain>/skills/<name>/`) and to the third-party skills installed in `../.agents/skills/`, copies of the skills marked `.install-as-copy`. The starter ships no skill. Regenerate with `tools/machine/update.sh`; edit nothing in it.
