# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- LLM calls in this project go through the user's Claude subscription (`claude -p`). Running `ingest` on new files,
  `ask`/`answer` without a cache hit, or re-extraction consumes usage. So does `benchmark`: its cached-repeat step
  runs `ask` on the first question 5 times against the real DB, which is up to 5 full answer runs (planner plus one
  or two narrations each) if the answer is not cached, or is never cached because it fails the post-check. Say
  what it will cost and get the user's OK first. Everything else is offline.
- When changing behaviour, prefer this loop: edit, `python -m pytest -q`, `python -m backbone verify-answers`.
  `verify-answers` is read-only; it exits non-zero if any saved result changed or any post-check fails.
  `--rewrite` refreshes the saved post-check fields and Markdown, so use it only when that is intended.
- For design questions, read `docs/agents/DECISIONS.md` before proposing alternatives. Several were tried or
  rejected deliberately (generic SQL compiler, last-write-wins, picking one value for disputed durations).
- For the live review call with Backbone, see `docs/agents/RUNBOOK.md`.
