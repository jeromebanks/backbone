# Runbook: the live review session

Backbone's follow-up is a ~30-minute system-design call. They will review the abstraction, trace conclusions back
to sources, and **run related questions and additional documents through the code**.

## Before the call

```bash
python -m pytest -q && python -m backbone verify-answers     # green, identical
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
bb ask "<question about it>"         # the answer cache is invalidated automatically (fingerprint includes doc hashes)
```

What to point out:
- Only the new document is extracted, and only its patient is re-reconciled (~4 ms).
- A byte-identical re-send counts as `duplicate_files`, with 0 LLM calls.
- Read `decisions` for the affected encounter to see how the new record was weighed. Is it a correction, a copy, a
  draft or a conflict?
- **A revised treatment plan** is supported. Weeks spanning the change are judged against each plan, and
  `compare(split="plan_change")` splits at the new plan.
- **A new patient** is keyed by MRN; collection-wide questions include them.

## If something goes wrong

- **Extraction fails or a schema error occurs:** `ingest` reports `failed` and continues. Rerun the file. Check `claude`
  login.
- **A claim is rejected by R0:** the quote was not found. Look in `decisions` for rule R0 and inspect the cached
  extraction in `cache/extractions/`.
- **The answer post-check is not OK:** the JSON lists the offending numbers or citations. Treat the narrative with
  caution; the `results` are still correct.

## Talking points (what reviewers grade)

| Criterion | Evidence |
|---|---|
| Completeness | all 5 questions plus 6 unseen ones answered |
| Accuracy | golden tests; ablation |
| Reproducible calculations | the `calculation` strings, `sql`, `verify-answers` |
| Evidence quality | verified quotes with line numbers; 0 unverified claims |
| Uncertainty | bounds and UNDETERMINED; `depends_on_unresolved`; unsupported questions refused |
| Follow-up performance | milliseconds to execute; 1 ms when cached; only new docs are extracted |
| Research judgment | DECISIONS.md, the ablation, the limitations and the scale estimates in the README |
