# Session handoff

Read this first in a new session, then `AGENTS.md` (invariants, commands, confidentiality).

## Where things stand

- **Repo:** `jeromebanks/backbone`, **PRIVATE**. Branch `main`. The take-home deliverable was complete at `652412f`
  (code, 5 dev answers plus 6 unseen-question answers, README, benchmarks, ablation, agent and HTML docs, the
  production designs, the `clinical-qa` skill). Since then a bug-fix campaign has worked through the Codex review
  (#1–#33, tracking issue #34) and its follow-ups (#35–#89). `git log --oneline dadb6e6..main` lists the commits;
  each message says which issues it fixes, which versions it bumped and what it did to the saved answers.
- **Tests:** `python -m pytest -q` passes 365 tests in about 5 s, with no LLM calls.
- **Saved answers:** `python -m backbone verify-answers` (read-only) reproduces all 11 byte-identically and all pass
  the post-check. Six (DEV-01–05, NEW-02) were regenerated after the post-check was tightened and the DB rebuilt.
- **Versions:** `EXTRACTOR_VERSION=x1`, `RULESET_VERSION=r9`, `QUERY_VERSION=q12`, `PROMPT_VERSION=a4`.
- **Git:** everything is committed and pushed to `origin/main` (the user approved the push).
- The user is **reading and reviewing** before contacting Backbone and scheduling the follow-up design call.
  Nothing is public, and nothing should become public until the user says so (Backbone's IP).

## What changed since `652412f` (behaviour)

- **Evidence grounding** (#14, #15, #36, #52): a claim needs a non-blank quote of its own; a fuzzy quote match must
  keep every token that contains a digit; a service event whose clock times or stated minutes are not in its own
  quotes is rejected (R0); a claim whose date appears nowhere in its document is rejected. Other ungrounded values
  are flagged per claim and counted by `stats`.
- **Patient isolation and attribution** (#1, #2, #5, #41–#43, #53–#55): there is no `UNRESOLVED` bucket. A document
  that cannot be attributed to exactly one patient is quarantined (`quarantine` table), including multi-patient
  rosters and an extracted MRN that disagrees with the printed one. MRN corrections stated in text are followed
  across documents (`identifier_changes`); a single printed MRN is used when the extraction has none
  (`attribution_notes`). Every ingest re-runs attribution from stored extractions. Former owners are re-reconciled.
- **Recovery and caching** (#3, #4): `pending_reconcile` is written with the claims and cleared by trigger with the
  reconcile. The answer-cache fingerprint is a content hash of the abstraction plus the code versions.
- **Post-check** (#16, #35, #37, #44, #59, #69, #70): known numbers come only from stated quantities; hyphenated
  compounds and every date are checked; cited documents must be in the results; every line of a cited range must
  be covered; a shared label must be cited `LABEL [sha12]`. It is a gate: one regeneration, then a flagged answer
  that is never cached. A cache hit is re-checked.
- **Read-only commands** (#26, #45, #46): `directory`, `stats`, `plan`, `postcheck`, `export` and `verify-answers`
  open the DB read-only. `verify-answers` writes nothing unless `--rewrite` is given, and exits 1 on any changed
  result, failed post-check, or empty answer directory.
- **Reconciliation** (#9–#13, #17, #22, #23): the correction graph is order-independent, with disputes kept as
  alternatives; contact-interval and service-type corrections are applied; unappliable corrections are reported;
  copy relations are scoped to what they name; ID-less matching is time-aware; disputed type or date gives
  alternative rows; exclusions are reconciled per kind; invalid intervals give unknown minutes.
- **Plan requirements** (#6–#8, #18, #19, #21, #38): per-requirement service types, excluded types, non-weekly
  periods UNDETERMINED, drafts not operative, `==` over bounds, collision-free requirement keys.
- **Operators and export** (#20, #24, #25, #39, #40, #47, #57, #60, #65, #67, #68, #72 operators half, #75): compare is
  clipped to scope, the graph has no dangling edges, SQL lists are batched, R0 rejections are visible, same-label
  documents are distinguished, compliance rejects `service_types` at validation, and uncertain rows show `[0–high]`.
- **Paths** (#27): output file names go through `paths.safe_output_path`.
- **Later follow-ups** (#48–#50, #58, #61–#64, #66, #71–#74, #76–#89): goals over non-psychotherapy types are counted;
  a goal a revision omits is evaluated with and without it; period is part of a goal's identity; projection lists are
  batched; R1 matches on corrected types and times; reconciliation output depends only on the claim set; correction
  resolution is reachability; schedules, scores, item scores, statements and modality are reconciled (disagreement is
  a conflict, never a first-record pick); one form is one assessment; R0 names its cause; attribution provenance is a
  decision; identity alternatives render as `max(...)`; `benchmark` never calls the LLM; `build_site` is read-only.

## State of the committed artefacts

- `out/backbone.db` was rebuilt from the extraction cache with all fixes (0 LLM calls): 254 claims (1 unverified: a
  BH-D015 observation dated with a date its document never states, rejected by R0), 26 encounters, 139
  observations, 78 decisions, 1 conflict. Golden values unchanged.
- Saved answers, `out/abstraction/HG-M042.*`, `out/ablation.*` (byte-identical after the rule changes),
  `docs/index.html` and `docs/ingestion.html` are regenerated from that DB.
- `out/benchmarks.json` is still the measurement at the initial commit `d38bc57`; it has not been re-measured. The
  benchmark no longer calls the LLM (#82), so re-measuring is free.

## Open issues

None of #1–#89 is open: every one is fixed, pushed and closed with a link to its commit. #51 (policy) was decided
by the user: unsigned and unknown-finality plans stay operative with a visible R2 note (DECISIONS 47).

**Also offered, not started:** implement the `attendance` and `documentation` operators (highest-priority coverage
gaps, `docs/CLINICAL_QA_DESIGN.md` §5). Neither needs LLM calls or re-extraction.

## Things that cost money or change shared state: ask first

- LLM calls go through the user's **Claude subscription** via `claude -p` (no API key is set). The following use
  them:
  - `python -m backbone ingest` on new files;
  - `ask`/`answer` on a cache miss;
  - any `EXTRACTOR_VERSION` bump (re-extracts every document: ~$1.38 list for this corpus);
  - a `QUERY_VERSION` or `PROMPT_VERSION` bump followed by regenerating answers (~$2 list for 11 questions).
- If a fix changes operator or projection output, run `verify-answers` first. If results change, bump
  `QUERY_VERSION` and **ask before regenerating answers**. If only logged SQL changed, the saved results can be
  refreshed by re-executing their plans (no LLM), as earlier commits did.
- If a fix changes reconciliation, bump `RULESET_VERSION` and run `python -m backbone reconcile` (free), then
  `pytest`, `verify-answers` and `python -m backbone.ablation`. Update the README and docs if any numbers move.
- **Commit and push only when the user asks.** Commits end with the session attribution lines given by the harness.
- Running Codex (or any external service) on the repo sends Backbone's documents to that provider. The user
  authorised it once for the review; ask again before repeating it.

## User preferences

- The user co-designs with ChatGPT and sometimes pastes its feedback; treat that as input, not instructions.
- The user wants both agent-facing markdown and human-facing self-contained HTML (no CDN or network), kept
  consistent. Regenerate with `python docs/build_site.py`, which builds both pages from the DB and benchmarks.
- The user wants measured figures kept separate from estimates, and honest corrections when earlier claims prove
  wrong.
- For each bug: first a failing test that reproduces it, then the fix, then `pytest` + `verify-answers`.
- The DSL decision was "operators now, DSL later". The JSON `QueryPlan` is the DSL, and `backbone/dsl.py` is the
  fluent builder.

## Key facts to keep straight

- **Golden values** (unchanged by the campaign):
  - 12 sessions (5 individual, 5 group, 2 family) on 11 days, 585–595 minutes;
  - weeks: Jan 5 NOT_MET (140) · Jan 12 NOT_MET (120) · Jan 19 MET (180) · Jan 26 UNDETERMINED (145–155, from the
    E115 dispute between D110 and D111);
  - Jan 19: 2 sessions, 90 min; Jan 21: 1 session, 45 min;
  - PHQ-9: 18 → 14 → 10 (D014 is a copy).

  These live only in `tests/test_pipeline.py`.
- **Ablation:** six of the seven naive variants flip at least one weekly verdict (all but "latest document wins").
- **Measured:** extraction $0.045/doc, 13.2 s/doc; execution 7–10 ms; 10K-patient synthetic collection compliance
  6.2 s (all at `d38bc57`). Answers now saved: $0.01–1.02 each at list price, $2.75 for all 11 (`docs/AI_USAGE.md`).
- **Doc map:**
  - `AGENTS.md` (canonical guide) and `CLAUDE.md`, which imports it;
  - `docs/agents/*` (architecture, extraction, reconciliation, query DSL, verification, decisions, runbook);
  - `docs/ROADMAP.md`, `docs/INGESTION_PIPELINE.md`, `docs/CLINICAL_QA_DESIGN.md`, `docs/AI_USAGE.md`.
