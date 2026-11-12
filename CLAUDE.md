# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- LLM calls in this project go through the user's Claude subscription (`claude -p`). Running `ingest` on new files,
  `ask`/`answer` without a cache hit, or re-extraction consumes usage. Say what it will cost and get the user's OK
  first. Everything else is offline.
- When changing behaviour, prefer this loop: edit, `python -m pytest -q`, `python -m backbone verify-answers`.
- For design questions, read `docs/agents/DECISIONS.md` before proposing alternatives. Several were tried or
  rejected deliberately (generic SQL compiler, last-write-wins, picking one value for disputed durations).
- For the live review call with Backbone, see `docs/agents/RUNBOOK.md`.
