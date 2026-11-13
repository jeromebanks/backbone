# Query DSL, operators and answering

## The DSL is `QueryPlan` (`backbone/query.py`)

```python
Scope(patients=["HG-M042"] | "all", start=date, end=date,
      service_types=[...] | None, include_excluded=False, include_evidence=True)

CareStep(scope, group_by="none|service_type|day|week|patient")
ComplianceStep(scope, consecutive_below=None|N>=2)   # scope.service_types is rejected at validation (#47)
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
| `care` | `select_encounters`, `aggregate` | totals with bounds, `by_service_type`, groups (bucketed once), facts per encounter (an `uncertain` row adds `counted_minutes`, its 0..high contribution, #65), exclusions with records (plus R0-rejected claims when `include_excluded`), R0–R4/R7/R9 decisions, evidence |
| `compliance` | `weekly_compliance`, `consecutive_runs` | rejects `scope.service_types` (each goal counts the types its plan states; validation error since #47, an `unsupported` envelope for unvalidated steps); weeks (status, evaluations per requirement set, `minutes_calculation`, notes), runs, exclusions, R2/R3/R4/R9 decisions, plan evidence |
| `timeline` | encounters, claims, relations, assessments, observations | documents with what each asserted (disposition, arrival/departure, intervals) and corrections/retransmissions; an assertion is listed under the primary encounter row when it is shown, with `identity_alternatives` naming the shown `~` alternative rows that share the claim (#67); assessments with `copies_not_counted`; `exclusions` lists R0-rejected claims in scope (dated by a date the claim's document states; a claim with none, or whose date ingest found nowhere in its document (`unverified_absent`, #52/#68, named in `unstated_dates`), is listed for every scope, flagged `undated: true`, after the dated ones and with a note (#60); a claim's service type must match `service_types`) |
| `compare` | `plan_change_dates`, `aggregate` | before/after totals, minutes per week, by type, conflicts, evidence. `split="plan_change"` splits at the first day in (start, end] on which a non-empty requirement set different from the previous day's takes effect (a revision, a first plan starting inside the scope, a plan resuming after a gap; compared by requirement signature, so an identical restatement is no change). A day on which requirements simply stop applying is not a change. Later changes are named in a note but not split; no change gives an explicit note. Both sides are clipped to the scope; a split outside it gives one side and a note |

Rules for operators:
- They take semantics only from `project.py` and never re-derive eligibility or minutes.
- They use parameterized SQL only, recorded through `SqlLog.run`, so the envelope's `sql` lists exactly the statements
  its result depends on. `execute_plan` passes each step a plan-wide `cache`: the corpus-wide shared-label set (#57)
  is computed by the first step that needs it and reused by later steps, which still list its statement. A step's
  `sql` therefore does not depend on which steps ran before it. The cache lives for one `execute_plan` call only.
- Minute expressions (`minutes_calculation`, `calculation`) show each row's contribution from
  `project.contribution`, so an `uncertain` row reads `[0–50]`, never a definite `50` (#65).
- Cap per-row detail with `_cap` (`DETAIL_LIMIT = 200`), with a note that says what still covers every row (`totals`,
  `groups`) or that nothing does (exclusions, documents, assessments, observations, rejected claims; #60), in every operator (timeline caps encounters,
  documents, assessments, observations and rejected claims; compare caps facts and exclusions, never its per-side
  groups, which are its totals). Totals stay complete; conflicts, decisions and evidence follow the shown rows.
- Build every `IN (...)` list through `_batches(conn, items, reserved=…)`. It splits lists at the connection's
  SQLite variable limit (999 on old builds). A list that fits stays one statement, so the logged SQL is unchanged.
  Re-sort merged rows on the statement's ORDER BY. `tests/test_operators_export.py` checks that batched and single
  runs give the same results.
- Output must be deterministic: sort everything, and include no timestamps.
- Identity: `documents.sha256` identifies a document (`doc_label` is display only and not unique), and an encounter ID is unique only within a patient. Join and group by sha256, and match encounter IDs together with the MRN (or use the `mrn|id` encounter key). `tests/test_isolation.py` covers this for `timeline`.
- Same-label documents (#40): `doc_id` stays the label. When a label is carried by more than one document in the
  corpus, evidence entries and timeline document facts gain `doc_sha` (sha256[:12]), and label lists (`records`,
  `recorded_in`, `copies_not_counted`, `documents`) name the document `LABEL [sha12]`. Unique labels are
  unchanged. The post-check keys evidence by `(doc_id, doc_sha)` and requires such a document to be cited as
  `LABEL [sha12]` (#59).

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
  only numbers from the results, no new arithmetic (including compounds such as a derived "10-minute" gap), only
  dates the results state (no derived dates such as the days after a period ends), cite `(DOC-ID L<lines>)` using
  only listed line numbers (never a range over non-adjacent lines: `L6–7, L9`, not `L6–9`), cite a shared label as
  `LABEL [sha12]`, separate fact from interpretation, and list exclusions. These are instructions; the post-check
  below is what is enforced.
- `postcheck` checks these things against the results **minus the echoed `question`, `plan`, each step's
  `params` and SQL text**, so a number or document the asker typed cannot back itself. A parameter value counts only
  where the operator also states it in its computed output:
  - Every number in the narrative (excluding IDs such as `BH-D103` or `PHQ-9`, unidentified-contact keys, line
    refs, short shas, and calendar notation: ISO dates and datetimes, clock times, `1/7/2026`, zero-padded `01-26`,
    month-name dates including day lists such as `Jan 8, 15 and 27`, `January 2026`) must be a number the results
    **state** (`_known_numbers`, #44): any JSON number, or a free-standing number in a human-readable string
    (calculations, reasons, notes, statements, evidence quotes). Identifier fields (`claim_id`, `doc_id`, `file`,
    `lines`, `rule`, `requirement`, `*_key`, `*_id`, `*_sha` …) contribute nothing, and inside strings the same
    calendar notation plus year-less `1/7`, keys (`MRN|…`), claim IDs, hex and label-like tokens (`BH-D103`, `PHQ-9`,
    `note_88.txt`) are removed first. Before #44 an unanchored digit scan admitted the digits of hex, keys and dates
    (on DEV-01, 71 of the integers 0–200; now 20). Numbers joined to a hyphen are checked too: `10-minute` and both
    ends of `30-45` (#69). A year-less `4/5` in the answer is checked as two numbers (it may be a ratio).
  - Cited labels are matched against **the corpus's own document labels**, optionally followed by `[sha12]`. A
    cited document that does not appear in the results (`documents_not_in_results`) fails the check, as does a
    `[sha12]` that no document with that label has (`unknown_documents`), and a label several documents share cited
    without `[sha12]` (`ambiguous_citations`, #59).
  - Every line of every `L<a>` or `L<a>–<b>` in a citation group must fall inside an evidence passage for that
    document. Adjacent passages may together cover a range; a reversed range fails. Passages are keyed by
    `(doc_id, doc_sha)`, so two same-label documents never back each other's lines (#59).
  - Every date in the narrative (ISO, `m/d/yyyy`, zero-padded `01-26`, `January 7, 2026`, `Jan 26–Feb 1`, day lists,
    `26 January 2026`) must be stated in the computed output, be a `start`/`end` of some step's scope, or be the last
    day (Sunday) of a Monday–Sunday week the results report (`dates_not_in_results`, #70). A year-less date matches
    any year.
  - It does **not** check: whether a backed number or date is attached to the right week, encounter or patient (any
    number in an evidence quote counts as stated); numbers written as words; clock times; uncited statements;
    prose, interpretation or causation.
- The post-check is a gate in `answer_question`. A failing narration is regenerated once, on the same results, with
  the failures and the previous answer in the prompt. If it still fails, the answer is returned with
  `postcheck.ok = false`, a warning banner in its Markdown, and is **not** cached. On a cache hit the post-check is
  **re-run** (not read from the row), so an answer cached under an older, looser check is a miss if it now fails. `postcheck_attempts` and `postcheck_first_attempt` record what happened.
- Cache key: `sha256(question + fingerprint)`. The fingerprint hashes the extractor, ruleset, query and prompt
  versions plus the abstraction's content: documents (minus text and timestamps), committed extraction identities
  (sha256, extractor version, model), claims, and every derived clinical table, excluding rowids and timestamps.
  A retried extraction, another model, or a reconcile that changes derived rows invalidates the cache; an identical
  rebuild does not. It costs ~2 ms on the supplied corpus, and ~1 s for a 10K-patient synthetic clone (260K
  encounters, no claims). At real scale claims dominate; persisting per-patient content hashes at reconcile and
  ingest time would make it O(patients). Tables are listed explicitly in `_FP_TABLES`, so a new derived table must be
  added there.
- `verify_answers()` / `python -m backbone verify-answers` re-executes every saved plan, requires identical results
  JSON, and re-runs the post-check. It is read-only (read-only DB connection, no files written) and exits 1 if any
  result differs or any post-check fails, or when it finds no saved answer with a plan (#46). `--rewrite` (`rewrite=True`) refreshes each saved answer's post-check
  field and Markdown.
- Output file names come from question IDs (`answer_file`) and MRNs (`export`). `backbone/paths.safe_output_path`
  accepts only `[A-Za-z0-9][A-Za-z0-9._-]*` without `..`, and requires the resolved path to stay inside the output
  directory. `answer_file` validates every ID (and rejects missing or duplicate IDs) before the first LLM call.

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
- The post-check validates numbers, dates and citations by set membership, not prose claims or which event a
  number belongs to.
- The narrator receives the full evidence JSON (13K–97K input tokens on the 5 development questions, measured at the
  initial commit).
