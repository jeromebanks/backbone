# Query DSL, operators and answering

## The DSL is `QueryPlan` (`backbone/query.py`)

```python
Scope(patients=["HG-M042"] | "all", start=date, end=date,
      service_types=[...] | None, include_excluded=False, include_evidence=True)

CareStep(scope, group_by="none|service_type|day|week|patient")
ComplianceStep(scope, consecutive_below=None|N>=2)
TimelineStep(scope, kinds=[encounters|documents|decisions|assessments|observations], observation_domains=None)
CompareStep(scope, split=date | "plan_change")

QueryPlan(question, steps=[Step, ...], unsupported_reason=None)   # .explain()
execute_plan(conn, plan) -> {"question", "plan", "results": [envelope, ...]}
```

All models use `extra="forbid"`. `Step` is a discriminated union on `op`, so unknown operations fail validation.
There are two front-ends that build the **same object**:
- the LLM planner in `answer.py` (JSON validated against the schema);
- the fluent builder in `dsl.py`: `care.for_patient(m).during(a, b).include_excluded().care("week").compliance(2)`.
  It also offers `.on(day)`, `.of_types(...)`, `.without_evidence()`, `.timeline(...)`, `.compare(...)`, and the
  terminals `.plan()`, `.explain()`, `.execute(conn)` and `.to_sql(conn)`.

## Operators (`backbone/operators.py`)

| op | uses | notable output |
|---|---|---|
| `care` | `select_encounters`, `aggregate` | totals with bounds, `by_service_type`, groups (bucketed once), facts per encounter, exclusions with records, R0–R4/R7/R9 decisions, evidence |
| `compliance` | `weekly_compliance`, `consecutive_runs` | weeks (status, evaluations per requirement set, `minutes_calculation`, notes), runs, exclusions, R2/R3/R4/R9 decisions, plan evidence |
| `timeline` | encounters, claims, relations, assessments, observations | documents with what each asserted (disposition, arrival/departure, intervals) and corrections/retransmissions; assessments with `copies_not_counted` |
| `compare` | `plan_change_dates`, `aggregate` | before/after totals, minutes per week, by type, conflicts, evidence; an explicit note when there is no plan change |

Rules for operators:
- They take semantics only from `project.py` and never re-derive eligibility or minutes.
- They use parameterized SQL only, recorded through `SqlLog.run` so the envelope's `sql` is exact.
- Cap per-row detail with `_cap` (`DETAIL_LIMIT = 200`), with a note. Totals stay complete. Keep `IN (...)` lists
  bounded, since SQLite has a variable limit.
- Output must be deterministic: sort everything, and include no timestamps.

## Adding an operator

1. Define a `XStep(Strict)` with `op: Literal["x"]` and fields with descriptions (the descriptions reach the planner
   through the JSON schema). Add it to the `Step` union.
2. Implement `def x(conn, step) -> dict` in `operators.py` using `_envelope`. Register it in `execute_plan`.
3. Describe it in `PLANNER_SYSTEM` (`answer.py`). Bump `QUERY_VERSION` and `PROMPT_VERSION`.
4. Add a no-LLM test using `execute_plan` (see `tests/test_pipeline.py`), plus a fluent-DSL method if useful.

## Answer pipeline (`backbone/answer.py`)

- `directory(conn)`: the planner sees patients (MRN, name, DOB, document count, encounter range, plan effective
  ranges). It never sees document text.
- The planner (effort `medium`) produces a `QueryPlan`, and `question` is overwritten with the user's text. If
  there are no steps and `unsupported_reason` is set, the answer is "Not answerable with the supported operations".
- The narrator (effort `medium`) produces `NarrativeOut{answer_markdown, unresolved[], caveats}`. It is given rules:
  only numbers from the results, no new arithmetic, cite `(DOC-ID L<lines>)`, separate fact from interpretation, and
  list exclusions.
- `postcheck` checks three things:
  - Every number in the narrative (excluding IDs, line refs, ISO dates, clock times and month-name dates) must
    appear in the results.
  - Cited labels are matched against **the corpus's own document labels**.
  - Every `L<n>` in a citation group must fall inside an evidence passage for that document. Problems are reported,
    not auto-fixed.
- Cache key: `sha256(question + fingerprint)`, where the fingerprint covers the extractor, ruleset, query and prompt
  versions plus all document hashes.
- `verify_answers()` / `python -m backbone verify-answers` re-executes every saved plan, requires identical results
  JSON, and re-runs the post-check.

## Known gaps

- There is no second planning round: if the first plan misses something, the narrator says what the results lack.
- The post-check validates numbers and citations, not prose claims.
- The narrator receives the full evidence JSON (13K–97K input tokens).
