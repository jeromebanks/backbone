# Verification

## Test suites (`python -m pytest -q`: ~1 s, zero LLM calls)

| File | What | How |
|---|---|---|
| `tests/test_rules.py` | interval algebra, quote verification, R0–R8 and verdict logic | hand-built claims via `tests/helpers.py`; no DB |
| `tests/test_pipeline.py` | golden end-to-end results, idempotency, near-duplicates, second patient, restart, determinism, DSL parity, plan revisions, agent CLI (`plan --summary`, `postcheck`, invalid plans), skill example plans | temp DB rebuilt from `cache/extractions/` (LLM calls monkeypatched to fail) |

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

- `python -m backbone verify-answers`: all 11 saved answers re-execute with identical results; post-check OK.
- `python -m backbone benchmark [--synthetic-patients N]` writes `out/benchmarks.json`. The synthetic section
  clones the reconciled layer (the query layer only) and is labelled SYNTHETIC.
- `python -m backbone.ablation` writes `out/ablation.md`: weekly verdicts under seven naive rules. The README
  quotes it.

## When you change something

| Changed | Run |
|---|---|
| anything | `pytest` |
| query/projection/operators | `verify-answers`. If results changed, bump `QUERY_VERSION`; regenerating answers needs the user's OK (LLM cost) |
| reconcile rules | bump `RULESET_VERSION`, `python -m backbone reconcile`, `pytest`, `verify-answers`, ablation |
| numbers/design shown to humans | `python docs/build_site.py`, README |
