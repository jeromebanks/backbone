# Verification

## Test suites (`python -m pytest -q`: a few seconds, zero LLM calls)

| File | What | How |
|---|---|---|
| `tests/test_rules.py` | interval algebra, quote verification, R0–R8 and verdict logic | hand-built claims via `tests/helpers.py`; no DB |
| `tests/test_grounding.py` | evidence grounding: claims without quotes fail R0, fuzzy matches can't change digits or IDs, post-check rejects question-only numbers, uncited documents and partially covered ranges | hand-built extractions, temp DB; no cache needed |
| `tests/test_pipeline.py` | golden end-to-end results, no corpus document quarantined, idempotency, near-duplicates, second patient, restart, determinism, DSL parity, plan revisions, agent CLI (`plan --summary`, `postcheck`, invalid plans), skill example plans | temp DB rebuilt from `cache/extractions/` (LLM calls monkeypatched to fail) |
| `tests/test_attribution.py` | patient attribution at ingest: MRN-less patients stay separate (quarantined), name match must be unique, multi-MRN rosters quarantined, the guard matches no corpus document text, re-extraction that moves a document clears the former patient (issues #1, #5) | temp DB, hand-built `Extraction`s via a monkeypatched `extract_document`; no LLM |
| `tests/test_isolation.py` | query-layer isolation: two patients sharing an encounter ID and a document label, and two same-label documents of one patient; timeline relations stay with their own patient and document | temp DB from hand-built `Extraction`s (`extract_document` monkeypatched); no cache, no LLM |
| `tests/test_answer_pipeline.py` | content fingerprint (#4), read-only `verify-answers` and its exit codes (#26), safe output paths (#27), the post-check gate with one regeneration (#35), step params excluded from known numbers (#37) | planner/narrator stubbed (`complete_json`); fingerprint tests ingest from the extraction cache |
| `tests/test_plan_requirements.py` | per-requirement service types, excluded types, non-weekly periods, drafts not operative, `==` over bounds, multi-goal plan keys, compliance service-type scope (#6, #7, #8, #18, #19, #21, #38) | hand-built claims; no LLM |
| `tests/test_ingest_robustness.py` | crash recovery via `pending_reconcile` (#3), value grounding (#36), re-attribution of quarantined documents (#41), roster and MRN-correction guards (#42), extracted-vs-printed MRN (#43) | temp DBs, monkeypatched extractor; corpus checks replay the cache |
| `tests/test_operators_export.py` | compare scope clipping (#20), graph integrity (#24), SQLite variable limits and detail caps (#25), R0 rejections in output (#39), same-label documents (#40) | real ingest + reconcile with a fake extractor |
| `tests/test_corrections.py` | R3 correction graph in every claim order, applied contact-interval and service-type corrections, scoped copy relations, correction provenance (#9, #10, #22, #23) | hand-built claims |
| `tests/test_encounter_minutes.py` | time-aware ID-less matching, disputed identity as alternative rows, per-kind exclusions, invalid intervals (#11, #12, #13, #17) | hand-built claims |
| `tests/test_followups.py` | post-check number pool (#44), read-only CLI commands (#45), `verify-answers` with nothing to verify (#46), absent dates (#52), MRN corrections across documents (#53), free-text and whitespace rosters (#54), printed-MRN fallback (#55), `stats` reporting (#56) | temp DBs, monkeypatched extractor |
| `tests/test_operator_followups.py` | compliance rejects `service_types` at validation (#47), per-plan shared-label cache (#57), cap notes, undated R0 rejections, export stability, batched timeline lookups (#60), uncertain rows' minutes (#65), identity alternatives in the timeline (#67) | hand-built claims in a temp DB |
| `tests/test_summary.py` | `plan --summary` shows uncertain contributions, undated rejections and identity alternatives (#75), and survives a requirement without a metric (#72) | synthetic results envelopes |
| `tests/test_llm_retry.py` | a validation failure is fed back to the next LLM attempt | stubbed backend |

## Golden values (derived by hand from `documents/` before coding; they live ONLY in `test_pipeline.py`)

- 12 sessions (5 individual, 5 group, 2 family), 11 days, 585–595 minutes.
- Weeks: Jan 5 NOT_MET (3 days, 140 min) · Jan 12 NOT_MET (2, 120) · Jan 19 MET (3, 180) · Jan 26 UNDETERMINED (3, 145–155).
- Two consecutive weeks below goal is `yes` (definite).
- Jan 19: 2 sessions, 90 min. Jan 21: 1 session, 45 min.
- PHQ-9: 18 (Jan 5), 14 (Jan 16), 10 (Jan 30). BH-D014 is a copy.

If a change moves any of these, it is either a bug or a deliberate semantic change. A deliberate change needs
justification in `DECISIONS.md` and an update to the README results.

## Scenario tests worth knowing

- **Duplicate file:** byte-identical; recorded as an extra path; totals unchanged.
- **Near-duplicate:** renamed and re-whitespaced; extracted as new (the extraction is replayed); encounter-level
  reconciliation absorbs it.
- **Second patient:** a different MRN leaves Rowan's results byte-identical; collection-wide `care` shows both.
- **Plan revisions:**
  - A mid-week revision is judged on the whole week against each plan.
  - A restated identical goal is no change.
  - Same-start conflicting goals give UNDETERMINED.
- **Restart:** a subprocess runs `python -m backbone plan` on the DB.

## Other checks

- `python -m backbone verify-answers` (read-only; `--rewrite` refreshes the saved post-check fields and Markdown):
  every saved plan must re-execute to identical results and every saved narrative must pass the current post-check,
  else it exits 1 (also when there is nothing to verify). All 11 saved answers pass (six were regenerated after the post-check was tightened).
- `python -m backbone benchmark [--synthetic-patients N]` writes `out/benchmarks.json`. The synthetic section
  clones the reconciled layer (the query layer only) and is labelled SYNTHETIC.
- `python -m backbone.ablation` writes `out/ablation.{md,json}`: weekly verdicts under seven naive rules (six of
  the seven flip at least one verdict). It works on a temporary copy of `out/backbone.db`. The README quotes it.
- `python -m backbone benchmark` also times 5 cached repeats of the first question through `answer_question`
  against the real DB. With no passing cache entry for it, that is up to 5 full LLM answer runs (ask first).

## When you change something

| Changed | Run |
|---|---|
| anything | `pytest` |
| query/projection/operators | `verify-answers`. If results changed, bump `QUERY_VERSION`; regenerating answers needs the user's OK (LLM cost) |
| reconcile rules | bump `RULESET_VERSION`, `python -m backbone reconcile`, `pytest`, `verify-answers`, ablation |
| numbers/design shown to humans | `python docs/build_site.py`, README |
