# AGENTS.md — working in this repository

Guide for coding agents (Claude Code, Codex, others). `CLAUDE.md` imports this file; keep it as the single source.
Deeper references live in [`docs/agents/`](docs/agents/README.md). Production plans: [`docs/ROADMAP.md`](docs/ROADMAP.md),
[`docs/INGESTION_PIPELINE.md`](docs/INGESTION_PIPELINE.md), [`docs/CLINICAL_QA_DESIGN.md`](docs/CLINICAL_QA_DESIGN.md). Human-facing docs: `docs/index.html`, `docs/ingestion.html`.

## Confidentiality (read first)

This is a **private** take-home submission for Backbone. The problem statement, `questions.json` and everything
under `documents/` are Backbone's material (synthetic patient data, but their IP).

- Never make the GitHub repo public, change its visibility, fork it publicly, or push to any other remote.
- Never publish repo content anywhere: no gists, pastebins, public artifacts or hosted pages, and no issues on other repos.
- Never send document text to services other than the configured LLM backend (`backbone/llm.py`).
- `docs/index.html` is self-contained on purpose: no CDN, fonts or analytics. Keep it that way.

## What this is

A pipeline that turns overlapping, contradictory clinical documents into a persisted, auditable **clinical
abstraction**, then answers questions with **deterministic computation** over it.

```
documents/ → ingest (sha256) → extract (LLM, 1 call/doc, cached) → claims + verified line spans   [evidence layer]
          → reconcile (pure Python rules R0–R9) → encounters, intervals, plans, assessments, decisions [clinical layer]
          → project.py (bounds, Mon–Sun weeks, plan-in-effect, MET/NOT_MET/UNDETERMINED)            [shared semantics]
question  → LLM → QueryPlan (typed JSON DSL) → 4 operators (read-only SQL) → results envelope
          → LLM narrates from results only → post-check (numbers, doc IDs, line refs)
```

## Commands

```bash
python -m pytest -q                                    # full test suite, no LLM, ~1 s — run after every change
python -m backbone verify-answers                      # saved answers must reproduce byte-identically (no LLM)
python -m backbone plan plans/weekly_compliance.json   # run a hand-written QueryPlan (no LLM)
python -m backbone stats | reconcile | export --patient HG-M042 | benchmark
python -m backbone directory | schema                 # patients in the abstraction; QueryPlan JSON schema
python -m backbone plan - --summary --out /tmp/r.json  # plan from stdin → compact readout + full results
python -m backbone postcheck answer.md --results /tmp/r.json   # numbers/citations in an answer must be backed
python -m backbone.ablation                            # naive-rule experiment → out/ablation.md
python docs/build_site.py                              # regenerate docs/index.html from the DB + benchmarks
# LLM-backed (uses Claude Opus 5.5 via `claude -p` = the user's subscription; costs usage — ask first):
python -m backbone ingest <paths>      # extracts only new sha256s; re-reconciles only affected patients
python -m backbone ask "<question>"    # answer cache hit = free
python -m backbone answer questions.json
```

Python ≥ 3.11, dependencies `pydantic` (+ `pytest`). SQLite at `out/backbone.db` (override with `--db` or
`BACKBONE_DB`). LLM backend: `BACKBONE_LLM=claude-cli` (default) or `anthropic-api` (needs `ANTHROPIC_API_KEY`;
implemented, never exercised).

## Where AI is used

Only `extract.py` (document → claims), and in `answer.py` the planner (question → QueryPlan) and the narrator
(results → answer). The `clinical-qa` skill makes Claude Code play the last two. Everything else is deterministic.
Never move a clinical decision or calculation into a prompt. Details, model choice and costs: `docs/AI_USAGE.md`.

## Invariants — do not break these

1. **The LLM never does arithmetic that reaches an answer.** Extraction records intervals and stated values.
   Minutes come from `intervals.py`, and counts and verdicts from `project.py`.
2. **Claims are not facts.** `claims` is append-only evidence. The clinical tables are derived by `reconcile.py` and
   must be fully rebuildable from claims. Never hand-edit derived tables.
3. **Precedence follows document relationships, never document date.** This covers explicit field corrections,
   retransmissions/copies and evidence tiers. There is no last-write-wins.
4. **Uncertainty is carried as `[low, high]` bounds.** Unknown never becomes 0. Verdicts are three-valued
   (MET if it holds at both bounds, NOT_MET at neither, else UNDETERMINED).
5. **Every quote is verified by code.** `evidence.py` locates it and computes line numbers. Unverifiable claims are
   dropped by rule R0. Never trust LLM-reported locations.
6. **No patient facts in prompts or production code.** No encounter IDs, names, dates or expected answers in
   `extract.py`, `answer.py` or the rules. Hand-derived expected values live **only** in `tests/test_pipeline.py`.
7. **Operators hold no clinical semantics.** Eligibility, minutes and plan logic live in `reconcile.py` and
   `project.py`. Operators select, aggregate via `project.py`, and format the envelope.
8. **The LLM never writes SQL or code.** Questions become a Pydantic-validated `QueryPlan`. Anything unsupported
   returns `unsupported_reason`.
9. **Determinism.** The same abstraction and plan give byte-identical results JSON (tested; `verify-answers`).

## Versioning and caches — bump when you change behaviour

| Change | Bump | Effect |
|---|---|---|
| extraction prompt or `schema.py` | `EXTRACTOR_VERSION` (`backbone/__init__.py`) | invalidates `cache/extractions/` → re-extraction costs LLM calls (~$0.045/doc) |
| reconciliation rules | `RULESET_VERSION` | then run `python -m backbone reconcile` (free, milliseconds) |
| operator/projection output | `QUERY_VERSION` | invalidates the answer cache; run `verify-answers` to see whether outputs changed |
| planner/narrator prompts | `PROMPT_VERSION` (`answer.py`) | invalidates the answer cache |

If a change leaves results identical (check with `verify-answers`), the saved answers stay valid.
Regenerating answers costs ~$2–3 at list price (11 questions) and needs the user's OK.

## Answering clinical questions in this repo

Use the **`clinical-qa` skill** (`.claude/skills/clinical-qa/SKILL.md`). The agent writes a QueryPlan, the CLI
computes it, and the agent writes a cited answer that must pass `postcheck`. Never compute clinical numbers by hand,
and never answer from raw `documents/`. Design for the production version: `docs/CLINICAL_QA_DESIGN.md`.

## Where to make common changes

- **New reconciliation rule:** `reconcile.py`. Emit a `res.decide(subject, "Rn", outcome, reason, claim_ids)` for
  every consequential choice. Add a fixture test in `tests/test_rules.py` using `tests/helpers.py`.
  See `docs/agents/RECONCILIATION.md`.
- **New operator or parameter:** add a step model in `query.py` (it joins the `Step` union), implement it in
  `operators.py` on top of `project.py`, register it in `execute_plan`, and describe it in `PLANNER_SYSTEM`
  (`answer.py`). See `docs/agents/QUERY_DSL.md`.
- **New extracted field:** `schema.py` + the `SYSTEM` prompt in `extract.py`, then bump `EXTRACTOR_VERSION`.
  Ask before re-extracting. See `docs/agents/EXTRACTION.md`.

## Gotchas

- `claude -p --json-schema` runs in strict mode and rejects the `discriminator` keyword. `llm._sanitize` strips it;
  Pydantic still validates the full model.
- The CLI runs from a temp cwd with `--setting-sources ""` and `--tools ""`, so no repo `CLAUDE.md` leaks into
  extraction prompts.
- `documents.sha256` is the identity. `doc_label` (header `Document ID`, else filename stem) is not unique: a
  near-duplicate copy shares the label.
- Encounter keys are `MRN|EncounterID`, or `MRN|U-<date>-<type>-<n>` for unidentified contacts.
- Collection-scale operators cap per-row detail at `DETAIL_LIMIT` (200) and add a note. Totals are always complete.
- Don't run the answer pipeline concurrently with benchmarks if you need clean latency numbers.

## Before you finish a change

`python -m pytest -q` passes · `python -m backbone verify-answers` (if query or projection code changed) ·
`python docs/build_site.py` (if numbers or design changed) · update README / `docs/agents` when behaviour changes.
Commit or push only when the user asks.
