# Runbook: the live review session

Backbone's follow-up is a ~30-minute system-design call. They will review the abstraction, trace conclusions back
to sources, and **run related questions and additional documents through the code**.

## Before the call

```bash
python -m pytest -q && python -m backbone verify-answers     # green; exit 0 = every saved result identical + post-check OK
claude -p "say ok" --model claude-opus-5-5                    # subscription login works (LLM path ready)
open docs/index.html                                          # human overview
```

Keep a scratch copy of the database so live ingests don't touch the committed one:

```bash
cp out/backbone.db /tmp/demo.db && alias bb='python -m backbone --db /tmp/demo.db'
```

## Tracing a conclusion (no LLM)

- **Why does week 4 say UNDETERMINED?** Run `bb plan plans/weekly_compliance.json`, then look at the
  `conflicts` → E115 candidates (BH-D110 vs BH-D111) and the `decisions` → R4 `minutes_disputed`.
- **Show the evidence for one encounter.** Open `out/abstraction/HG-M042.json`, find `encounters[]` → `records[]`,
  and use the `passages` line numbers. Open `documents/<file>` at those lines.
- **Show the SQL.** In Python:
  `from backbone.dsl import care; print(care.for_patient("HG-M042").on("2026-01-19").care().to_sql(conn))`.
- **Show the design experiment.** `out/ablation.md`.

## New questions (LLM: ~15–50 s each)

```bash
bb ask "How many minutes of group therapy did Rowan receive in the week of Jan 19, and why not 90 per session?"
bb ask "Which sessions were documented by more than one record?" --json | less
```

If a question is outside the operators, the system says so (`unsupported_reason`). That is intended behaviour.

## New documents (LLM: ~13 s per new document)

```bash
bb ingest path/to/new_doc.txt        # prints: new_documents, extracted_llm, affected_patients, reconcile summary
bb ask "<question about it>"         # cache miss: the fingerprint is a content hash of the whole abstraction
```

What to point out:
- Only the new document is extracted, and only its patient is re-reconciled (~4 ms).
- A byte-identical re-send counts as `duplicate_files`, with 0 LLM calls.
- Read `decisions` for the affected encounter to see how the new record was weighed. Is it a correction, a copy, a
  draft or a conflict?
- **A revised treatment plan** is supported. Weeks spanning the change are judged against each plan, and
  `compare(split="plan_change")` splits at the first day a new or different requirement set takes effect (a plan
  that just ends, with nothing in its place, is not a split point). A plan from a draft document is not operative.
- **A new patient** is keyed by MRN; collection-wide questions include them.
- **A document without a usable identity is quarantined, not guessed.** No MRN and no unique name (+ DOB) match,
  several patients named, or an extracted MRN that differs from the printed one: `ingest` prints `QUARANTINED` and
  lists it under `quarantined`, and `bb stats` counts it under `quarantined_documents`. Its claims count for nobody
  until a later ingest can attribute it. For a demo of a new patient, include an MRN in the document.

## If something goes wrong

- **Extraction fails or a schema error occurs:** `ingest` reports `failed` and continues. Rerun the file. Check `claude`
  login.
- **A claim is rejected by R0:** it has no quote of its own, a quote was not found (a fuzzy match that changes a
  digit does not count), a service event's clock times or stated minutes are not in its own quotes, or a date it
  carries appears nowhere in the document. Look in `decisions` for rule R0. Its reason currently reads "quote not
  found" whatever the cause (#68); the claim's `evidence` spans (`match: missing`) or its last, `grounding` entry
  (`absent` values, `unverified_absent`) show which check failed. Check
  `timeline` or `care` with `include_excluded` (rejections are listed as exclusions), and inspect the cached
  extraction in `cache/extractions/`.
- **The answer post-check is not OK:** `ask` has already regenerated the narrative once. The answer carries a
  warning banner, is not cached, and its `postcheck` lists the offending numbers, dates or citations. Treat the
  narrative with caution; the `results` are still what the engine computed.

## Talking points (what reviewers grade)

| Criterion | Evidence |
|---|---|
| Completeness | all 5 questions plus 6 unseen ones answered |
| Accuracy | golden tests; ablation |
| Reproducible calculations | the `calculation` strings, `sql`, `verify-answers` |
| Evidence quality | verified quotes with line numbers; 0 unverified claims | <!-- FINAL-NUMBERS -->
| Uncertainty | bounds and UNDETERMINED; `depends_on_unresolved`; unsupported questions refused |
| Follow-up performance | milliseconds to execute and to serve a cached answer; only new docs are extracted |
| Research judgment | DECISIONS.md, the ablation, the limitations and the scale estimates in the README |
