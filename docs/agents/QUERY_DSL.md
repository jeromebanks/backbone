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
- `postcheck` checks these things against the results **minus the echoed `question`, `plan` and SQL text**, so a
  number or document the asker typed cannot back itself:
  - Every number in the narrative (excluding IDs, line refs, ISO dates, clock times and month-name dates) must
    appear in the results (totals, groups, facts, calculations, exclusions, decisions, evidence quotes, notes).
  - Cited labels are matched against **the corpus's own document labels**. A cited document that does not appear
    in the results (`documents_not_in_results`) fails the check.
  - Every line of every `L<a>` or `L<a>–<b>` in a citation group must fall inside an evidence passage for that
    document. Adjacent passages may together cover a range; a reversed range fails. Problems are reported, not
    auto-fixed.
- Cache key: `sha256(question + fingerprint)`, where the fingerprint covers the extractor, ruleset, query and prompt
  versions plus all document hashes.
- `verify_answers()` / `python -m backbone verify-answers` re-executes every saved plan, requires identical results
  JSON, and re-runs the post-check.

## Agent workflow (Claude Code)

The `clinical-qa` skill (`.claude/skills/clinical-qa/`) answers questions with Claude as the planner and narrator,
and runs no LLM inside the CLI:

1. `python -m backbone directory`
2. write a QueryPlan
3. `python -m backbone plan <file|-> --summary --out r.json`
4. write the answer
5. `python -m backbone postcheck answer.md --results r.json`

The skill's example plans are validated by `tests/test_pipeline.py::test_skill_example_plans_stay_valid`; keep
them in sync when the DSL changes.

## Roadmap

Question-coverage gaps (what clinicians will ask that we can't answer) are in
[`docs/CLINICAL_QA_DESIGN.md`](../CLINICAL_QA_DESIGN.md) §5. The DSL roadmap that closes them is in §6:
- versioned schema;
- episode and relative scopes;
- new operators: `attendance`, `documentation`, `intervals`, `authorization`, `providers`, `coverage`,
  `assessment_change`, `cohort`;
- requirement types beyond weekly days/minutes/sessions (per-service frequency, deadlines, assessment cadence);
- modality, provider and month grouping and filters;
- step composition, normalization and plan caching;
- explain/estimate;
- SQL parity;
- permission stamping;
- a labelled retrieval operator.

## Known gaps

- **Coverage:** counts of no-shows, cancellations and non-therapy contacts; signature timeliness; authorization use;
  care by provider; time between events; modality and month grouping; non-weekly requirement types. None of these
  has an operator yet (see design §5). Until they exist, agents must **list** the relevant rows from the results and
  say the count is not computed. Never count by hand.

- There is no second planning round: if the first plan misses something, the narrator says what the results lack.
- The post-check validates numbers and citations, not prose claims.
- The narrator receives the full evidence JSON (13K–97K input tokens).
