# Backbone clinical abstraction prototype

Turns a pile of overlapping, contradictory clinical documents into a **persistent, auditable clinical abstraction**,
then answers questions with **deterministic computations over that abstraction**: every number traces to encounters,
reconciliation decisions, verified source passages and original files.

```
documents/ ─ingest (sha256)─► documents ─extract (LLM, cached per sha256)─► claims + verified line spans   evidence layer
                                                                              │
                                    reconcile (pure Python, versioned rules R0–R9, decisions + conflicts logged)
                                                                              ▼
                     encounters · intervals · plan requirements · assessments · observations                 clinical layer
                                                                              │
             projection (bounds, Mon–Sun weeks, plan in effect, MET / NOT_MET / UNDETERMINED)               shared semantics
                                                                              │
question ─LLM─► QueryPlan (typed JSON DSL, validated) ─► 4 operators (read-only parameterized SQL) ─► results envelope
                                                                              │
                                     LLM narrates ONLY from results ─► post-check gate (numbers, dates, documents, line refs)
```

**Docs:** open [`docs/index.html`](docs/index.html) for a visual overview, including an interactive encounter timeline
with the evidence behind every decision (self-contained, works offline). Agent and contributor guides are in
[`AGENTS.md`](AGENTS.md) and [`docs/agents/`](docs/agents/README.md). The path to production (design, stack, choke points, phases)
is in [`docs/ROADMAP.md`](docs/ROADMAP.md), with deeper designs for [ingestion](docs/INGESTION_PIPELINE.md) and
[clinician Q&A](docs/CLINICAL_QA_DESIGN.md). In Claude Code, ask clinical questions via the `clinical-qa` skill.

## Results on the development questions

Full answers with citations, plans, arithmetic and evidence tables: [`out/answers/ANSWERS.md`](out/answers/ANSWERS.md)
(and `out/answers/DEV-0x.md` per question). Every answer passed the post-check. <!-- FINAL-NUMBERS -->

| Week (Mon–Sun) | Therapy sessions counted (patient-present minutes) | Days | Minutes | Goal ≥3 days & ≥150 min |
|---|---|---|---|---|
| Jan 5–11 | E101 individual 50 · E102 group 45 (arrived 10:15, left 11:15, minus break) · E104 family 45 (two notes, one session) | 3 | 140 | **NOT MET** |
| Jan 12–18 | E105 group 75 · E107 individual 45 | 2 | 120 | **NOT MET** |
| Jan 19–25 | E110 group 60 (corrected departure 11:15) · E111 individual 30 · E112 video 20 + 25 (one session, two calls) · E113 group 45 (late) | 3 | 180 | **MET** |
| Jan 26–30 | E115 individual **40–50** (two signed notes disagree) · E118 group 75 · E119 family 30 (partner-only 15 min excluded) | 3 | **145–155** | **UNDETERMINED** |

- **DEV-01:** 12 sessions (5 individual, 5 group, 2 family) on 11 distinct days.
  - Excluded as not attended: no-shows E103 and E116 (D112's unsigned template note and posted charge are not
    attendance), clinic-cancelled E108, patient-cancelled E117.
  - Excluded as not therapy: partner-only collateral E109, professionals-only coordination E114, med management
    E106/E120, and outreach calls.
- **DEV-02:** 585–595 minutes (9.75–9.92 h). The only unsettled conclusion is E115 (40 vs 50 minutes).
- **DEV-03:** weeks 1–2 NOT MET, week 3 MET, week 4 UNDETERMINED: the days goal is met, but the minutes straddle 150.
- **DEV-04:**
  - Jan 19 has 2 contacts and 90 minutes. The correction (D103) overrides the original roster (D102); the later
    resend (D104) is a copy and does not revert the correction.
  - Jan 21 has 1 contact and 45 minutes: two platform calls under one appointment.
- **DEV-05:** three distinct PHQ-9s: 18 (Jan 5) → 14 (Jan 16, form HG-Q116) → 10 (Jan 30, item 9 = 0). D014 (Jan 26)
  is an import copy, not a new assessment.
  - The Jan 19 contact was added because Rowan became overwhelmed in group when discussion turned to work.
  - Supported: score decline, plus "some" and then "partial" improvement in the clinicians' words.
  - Not supported: remission, resolved avoidance or sleep, return to work, or attribution to any particular service.

These expected values were derived by hand from the source documents during planning, **before** any code existed.
They are the golden fixture in `tests/test_pipeline.py`, and they appear nowhere in production code.

Six **unseen** questions ([`out/answers/ANSWERS_questions_unseen.md`](out/answers/ANSWERS_questions_unseen.md))
exercise generalization: missed groups and why, days-met-but-minutes-not weeks, before/after Jan 19, a
collection-wide consecutive-weeks query, a plan-revision comparison (correctly reported as *no revision on file*),
and blood pressure (correctly **refused as unsupported** rather than improvised).

## Quick start

Requires Python ≥ 3.11 with `pydantic` (and `pytest` for tests). No other services.

```bash
pip install -e '.[dev]'          # or: uv sync --extra dev

# Everything below works offline: the extraction cache (cache/) and the database (out/) ship with the repo.
python -m pytest -q                                   # full test suite, no LLM calls
python -m backbone stats                              # what is in the abstraction
python -m backbone plan plans/weekly_compliance.json  # run a hand-written query plan (no LLM at all)
python -m backbone verify-answers                     # read-only: re-run every saved plan + post-check; exit 1 on any change or failure
python -m backbone verify-answers --rewrite           # also refresh the saved post-check fields and Markdown (results untouched)
python -m backbone export --patient HG-M042           # out/abstraction/HG-M042.json (+ .graph.json)
```

`verify-answers` opens the database read-only and writes no files unless `--rewrite` is given. It exits 1 when any
saved plan's results differ from the saved results, when any saved answer fails the current post-check, or when it
finds no saved answer to check. `python -m backbone benchmark` (writes `out/benchmarks.json`) is offline except for
its cached-repeat step, which asks the first development question 5 times against `out/backbone.db`: up to 5 full
LLM answer runs if that answer is not in the cache (or fails the post-check and so is never cached).

LLM-backed commands (new documents, new questions) use **Claude Opus 5.5**. By default they call Claude Code
headless (`claude -p`), which uses a Claude subscription login. All results here were produced that way.
`BACKBONE_LLM=anthropic-api` with `ANTHROPIC_API_KEY` switches to the Anthropic SDK (structured outputs, server-side
refusal fallback). That backend is implemented but was **not exercised** in this submission, because no API key
was available.

```bash
python -m backbone ingest documents/                  # re-run: 0 LLM calls (cache hit per sha256)
python -m backbone ingest path/to/new_note.txt        # extracts 1 doc, re-reconciles only that patient
python -m backbone ask "Which weeks met the day goal but not the minute goal?"
python -m backbone answer questions.json              # -> out/answers/DEV-0x.{md,json}, ANSWERS.md
```

**Adding documents never rebuilds the abstraction.** Ingest hashes each file; byte-identical files are recorded
as extra paths of the same document; only new hashes are extracted; only the patients whose evidence changed are
re-reconciled (milliseconds per patient). Patients whose evidence changed are marked pending in the same transaction
as the claims, so a crash before reconciliation is picked up by the next `ingest` or `reconcile`. A document that
cannot be attributed to exactly one patient is quarantined (kept as evidence, counted for nobody) and re-attributed
automatically once it can be. **New questions never re-read documents**: they compile to a `QueryPlan` over the saved
tables. Repeated questions are served from an answer cache keyed by the abstraction fingerprint, a content hash of
the documents, extractions, claims and derived tables plus the code versions; a cached answer is post-checked again
before it is served.

The query DSL can also be used directly from Python:

```python
from backbone.db import connect_readonly
from backbone.dsl import care

q = (care.for_patient("HG-M042").during("2026-01-05", "2026-01-30")
         .include_excluded().care(group_by="week").compliance(consecutive_below=2))
print(q.explain()); res = q.execute(connect_readonly()); print(q.to_sql(connect_readonly()))
```

## Approach

### 1. Evidence layer: claims, not facts
Each document is extracted **once**, by one LLM call with a strict JSON schema (`backbone/schema.py`), into what
*that document asserts*: document metadata (signed? draft? received when?), service events, explicit cross-record
relations, assessments, observations and treatment-plan requirements. The extraction prompt (`backbone/extract.py`)
is generic: it contains no patient facts, encounter IDs or answers. The model **never computes durations or resolves
conflicts**. It records intervals as written: scheduled times, arrival and departure, contact segments, breaks,
disconnections, and portions without the patient.

Every claim carries verbatim quotes. `backbone/evidence.py` locates each quote in the source text and converts it to
**line numbers computed by code**. A fuzzy match is accepted only if every token containing a digit (times, minutes,
IDs) is unchanged. A claim is rejected (rule R0) when it has no quote of its own, a quote cannot be found, a service
event's clock times or stated minutes are not in its own quotes, or a date it carries appears nowhere in its
document. Other values not stated in the claim's own quotes (typically a date taken from the header) are flagged,
not rejected. In this corpus 0 of the claims needed fuzzy matching and none were rejected. <!-- FINAL-NUMBERS -->

Cross-document links use only keys the text states, because one call sees one document. For example, D103 states
"departure for HG-E110 is 11:15, replacing 11:30", and D014 states "copied result from form HG-Q116 completed
2026-01-16". Reconciliation resolves those keys.

Each document is attributed to one patient by its MRN (checked against the MRN printed in the text), else by a
unique name (and DOB) match, else by the single MRN the text prints. An explicit "MRN X corrected to Y" moves every
document carrying X. A document that names several patients, or that matches none or several, is **quarantined**
instead of being guessed. No corpus document is quarantined.

Extractions are cached by `(sha256, extractor version, model)` in `cache/extractions/`, so the whole abstraction
rebuilds from scratch with zero LLM calls.

### 2. Clinical layer: deterministic reconciliation (`backbone/reconcile.py`)
A pure function from a patient's claims to encounters, intervals, plan requirements, assessments and observations.
Every consequential choice is written to `decisions`, and every unresolved disagreement to `conflicts`:

| Rule | What it does | Where it matters in this corpus |
|---|---|---|
| R0 | reject claims without a quote of their own, with a quote not in the source, with service-event times or stated minutes not in their own quotes, or with a date absent from the document | (none rejected) | <!-- FINAL-NUMBERS -->
| R1 | encounter identity by ID; an ID-less record joins the one encounter with the same date and type whose actual times overlap its own (when both state times); otherwise a separate contact. A disputed date or type becomes `uncertain` alternative rows, counted as at most one session, never a majority pick | D015/D103 mentions without IDs |
| R2 | drafts, templates and billing rows are not attendance evidence; requirements from a draft plan are not operative | D112 unsigned template + posted charge for no-show E116 |
| R3 | field-scoped explicit corrections (arrival, departure, disposition, contact interval, service type), resolved as a **graph** in any claim order: a chain ends at its last value; competing corrections or a cycle keep every alternative as disputed bounds plus a conflict; a correction that cannot be applied is reported. Retransmission and copy relations cover only the records they name. **Precedence follows relationships, never document date** | D103 corrects E110 departure; D104 (received later) is a resend of the uncorrected roster |
| R4 | evidence tiers (notes, registers, corrections, platform logs > schedule listings, notices); disagreement within the deciding tier becomes a **dispute carried as bounds**. Breaks, disconnections and absences are decided per kind by the first tier that states that kind; different accounts of one kind are alternatives, never summed | E115: D110 says 09:00–09:50, D111 says 09:10–09:50 |
| R5 | a session counts if it is psychotherapy, attended, with the patient present; unknown attendance is *uncertain*, never 0 | collateral (E109), coordination (E114), med management (E106, E120) |
| R6 | **minutes = present intervals − breaks − disconnections − patient-absent portions**; stated totals are only cross-checks. An inverted, overnight or incomplete interval gives unknown minutes with a flag, never a silent 0 | group breaks, late arrival (E113), partner-only 15 min (E119: note says 45, counted 30) |
| R7 | one patient cannot be in two places at once; overlaps are flagged | the superseded 11:30 departure would overlap E111 at 11:15, which supports the correction |
| R8 | assessments are identified by (instrument, completion date, form ID); imports and copies are not new assessments | D014 (filed Jan 26) copies the Jan 16 PHQ-9 |
| R9 | plan requirements apply by **effective date**: a revision supersedes earlier requirements from its effective date; identical restated goals count once; conflicting same-date goals are each evaluated. A week spanning a change is judged on **whole-week totals against each requirement set**, and is UNDETERMINED if they disagree. Each requirement counts its own service types; a period other than Mon–Sun weeks is UNDETERMINED (unsupported); `==` is MET only when both bounds equal the threshold | E101 at 09:00 precedes the plan signature (13:05) on the plan's first day; it is counted and the decision is logged. Mid-week revisions, restated goals and conflicts are tested on fixtures, since the corpus has a single plan |

### 3. Shared projection + typed query plans (the DSL)
`backbone/project.py` is the **only** place that turns encounters into numbers. Every quantity is a `[low, high]`
bound. Plan verdicts are mechanical: **MET** if the requirement holds at both bounds, **NOT_MET** if it holds at
neither, otherwise **UNDETERMINED**. "Unknown" never silently becomes 0.

Questions compile to a `QueryPlan` (`backbone/query.py`): a list of typed steps, each with a shared `Scope`
(patients or `"all"`, dates, service types (not allowed on `compliance`), include excluded records, include evidence).
There are four operators
(`backbone/operators.py`):

| op | returns |
|---|---|
| `care(group_by)` | sessions, distinct therapy days and minutes/hours with bounds, by type/day/week/patient; with `include_excluded`, every record that does not count and why |
| `compliance(consecutive_below)` | per Mon–Sun week: the goal in effect, delivered totals, MET/NOT_MET/UNDETERMINED, exclusions; runs of N weeks below goal, marked *definite* or *depends on unresolved documentation*. Each goal counts the service types its plan states, so a `service_types` scope is rejected at validation |
| `timeline(kinds)` | chronology of encounters, documents (and what each asserted), decisions, assessments, observations; a one-day scope reconstructs that day |
| `compare(split)` | care before vs after a date, or the first day a new or different treatment-plan requirement set takes effect (a plan ending with nothing in its place is not a change); both sides are clipped to the scope |

All operators return one machine-readable envelope: `totals`, `groups`, `facts`, `calculation` (human-readable
arithmetic), `exclusions`, `conflicts`, `decisions`, `evidence` (doc, file, lines, quote) and the exact
**parameterized SQL** executed. The LLM never writes SQL or code. A question the operators cannot express returns
`unsupported_reason` instead of an improvised answer (see NEW-06 below). `backbone/dsl.py` is a fluent Python
front-end that builds the identical `QueryPlan`.

### 4. Answering (`backbone/answer.py`)
1. The planner LLM call maps question → `QueryPlan`, validated against the schema.
2. Code executes the plan in milliseconds.
3. The narrator LLM call writes the answer **only from the results**, citing `(DOC-ID L<lines>)`.
4. A **post-check** gates the answer. It fails on a number (including in compounds such as "10-minute") or a date
   that the computed results do not state, a cited document that is unknown or not in the results, a shared label
   cited without its `[sha12]`, and any cited line not inside an evidence passage. A failing answer is regenerated
   once with the failures fed back; if it still fails it is returned with a warning banner and not cached. The
   check is set membership: it does not verify that a stated number belongs to the right week or event, and it
   does not check prose claims or causation.

Each answer file (`out/answers/DEV-0x.md`) shows the answer, the plan, the arithmetic, the post-check and a table of
every evidence passage.

## Design decision tested: interval algebra + relationship-aware precedence + bounds

The central bet: carry **intervals and document relationships** as evidence, derive minutes in code, and carry
unresolved disagreements as **bounds** instead of choosing a value. To test it, `python -m backbone.ablation` re-runs
the same projection after editing a copy of the reconciled encounters the way common naive rules would
(measured, `out/ablation.md`):

| Variant | W1 Jan 5 | W2 Jan 12 | W3 Jan 19 | W4 Jan 26 |
|---|---|---|---|---|
| **this system** | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 180m) | UNDETERMINED (3d, 145–155m) |
| scheduled group duration (ignore breaks, late arrival, early departure) | MET (3d, 185m) ⚠ | NOT_MET (2d, 135m) | MET (3d, 255m) | MET (3d, 160–170m) ⚠ |
| latest-received document wins (E110 departure 11:30 from the Jan 26 resend) | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 195m) | UNDETERMINED (3d, 145–155m) |
| draft note / posted charge counts as attendance (E116) | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 180m) | MET (4d, 220–230m) ⚠ |
| pick the primary note for disputed E115 (50 min) | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 180m) | MET (3d, 155m) ⚠ |
| pick the later-signed note for disputed E115 (40 min) | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 180m) | NOT_MET (3d, 145m) ⚠ |
| stated session length for E119 (45 min, incl. partner-only part) | NOT_MET (3d, 140m) | NOT_MET (2d, 120m) | MET (3d, 180m) | MET (3d, 160–170m) ⚠ |
| partner-only collateral counts as family therapy (E109, 40 min) | NOT_MET (3d, 140m) | MET (3d, 160m) ⚠ | MET (3d, 180m) | UNDETERMINED (3d, 145–155m) |

⚠ = verdict differs from this system.

**What I learned.** Six of the seven simple rules that seem reasonable (scheduled duration, a draft or posted charge
as attendance, picking either E115 note, the stated E119 session length, partner-only contact as family therapy)
change **at least one weekly verdict**. The seventh, "latest document wins", leaves the verdicts alone but changes
week 3's minutes (180 → 195) and creates an impossible overlap that R7 detects. Three of the four weekly verdicts are
fragile. Week 4 is the instructive case: a pipeline that picks *either* E115 note flips
week 4 to a confident MET or NOT_MET. The record supports neither, and the bounds make that visible instead of hiding
it. The same mechanism makes the answer to "who had two consecutive weeks below goal" robust: Rowan qualifies on
weeks 1–2 regardless of the week 4 dispute (`definite`, not `depends_on_unresolved`).

## Observed limitation and what I would investigate next

**Extraction is a single LLM pass, and its noise shows up as "unidentified contacts".** Passing mentions get
extracted as events: a cancellation notice mentions a later appointment, and a scheduling log mentions the next
visit. Most are matched to the right encounter by date + type (R1), but a few become extra non-therapy contacts
(e.g. `U-2026-01-16-other-1` from D016). They never count as therapy (a non-therapy type or unknown attendance can't
inflate totals), but they clutter the abstraction. A therapy-typed mention with no outcome would surface as
*uncertain* and widen bounds. That is honest, but noisy.

*Next investigation:* run extraction k=3 times (and with a cheaper model) on the corpus and measure **field-level
agreement** per event (date, type, disposition, intervals) against the reconciled encounters. Disagreement locates
unstable fields. Then either (a) add a cheap verification pass for low-agreement fields, or (b) tighten the schema
so a mention ("next appointment remains Jan 9") is a `reference`, not a `service_event`. The same harness gives the
data to choose the cheapest model that preserves this corpus's reconciled results, which is the main cost lever at scale.

**Also known:**
- Minutes are computed within one service date. An overnight, inverted or incomplete interval is not interpreted:
  it gives unknown minutes with a flag (bounded only by a valid schedule).
- Times are local, with no time-zone handling.
- Provider identity is not resolved: "N. Ellis" (desk staff) vs "Nora Ellis, LCSW" is deliberately not merged.
- Observation statements are LLM paraphrases (their quotes are verified).
- The narrator can still phrase interpretations. The post-check checks that numbers and dates appear in the
  results and that citations are backed by evidence passages. It does not check that a number is attached to the
  right week or event, numbers written as words, prose claims or causation.
- There is no second planning round if the first plan is insufficient.
- **Question coverage is narrower than a real review.**
  - There is no operator yet for: no-show and cancellation counts, signature timeliness, authorization use (the
    "8 authorized group sessions" in D001 was not extracted), care by provider, or time between events.
  - The posted charge for the no-show group is kept only as excluded evidence.
  - Ranked by priority in [`docs/CLINICAL_QA_DESIGN.md`](docs/CLINICAL_QA_DESIGN.md) §5.

## Performance (measured)

All figures below were measured on an Apple-silicon Mac (Darwin arm64, Python 3.12, SQLite 3.48). Raw numbers are in
[`out/benchmarks.json`](out/benchmarks.json) (`python -m backbone benchmark`). They were measured at the initial commit
(`d38bc57`), **before** the fixes for issues #1–#75, and have not been re-measured since. Some paths now do more work:
every answer lookup first hashes the abstraction's content (about 2 ms on this corpus, timed during development, not
benchmarked), a cache hit re-runs the post-check, and every ingest re-runs attribution for quarantined and
name-matched documents.

| What | Measured |
|---|---|
| Initial extraction, 31 documents (Claude Opus 5.5, effort high, 8 concurrent) | **58 s wall clock**; 13.2 s mean / 19.5 s p95 per document |
| Tokens per document | 8,318 input (≈90% fixed prompt + schema), 1,574 output |
| Extraction cost | API list-price equivalent **$1.38 total, $0.045/document** (reported by the CLI; the run used a Claude subscription) |
| Rebuild the whole abstraction from the extraction cache | 21 ms ingest + 4 ms reconcile, **0 LLM calls** |
| Re-ingest the unchanged corpus | 1 ms, 0 LLM calls, 0 patients re-reconciled |
| Add one document | 1 LLM call (~13 s) + 1.3 ms ingest + 4.3 ms to re-reconcile that one patient |
| Per-patient operators on the real abstraction (median) | care by week 0.4 ms · compliance 0.7 ms · reconstruct day 0.2 ms · symptom course 1.6 ms · care with exclusions + evidence 0.8 ms |
| Answering a new question end to end (5 dev questions) | **20–52 s**: plan 2.8–4.7 s (LLM) · **execute 7–10 ms** · narrate 15–49 s (LLM); list-price $0.08–0.62 per question |
| Repeating a question (answer cache) | **1.3 ms** median |
| Saved abstraction | 2.9 MB SQLite (`out/backbone.db`) + 136 KB extraction cache; 254 claims (0 unverified), 26 encounters, 77 decisions, 1 conflict | <!-- FINAL-NUMBERS -->

**Collection scale (SYNTHETIC).** The real patient's reconciled layer was cloned per patient. Documents and claims
were not cloned, so this measures the **query layer only**:

| Patients (encounters) | single-patient care / compliance | collection care by patient | collection weekly compliance + 2-week runs |
|---|---|---|---|
| 2,000 (52K) | 0.34 ms / 0.57 ms | 0.45 s | 0.93 s |
| 10,000 (260K) | 0.41 ms / 0.62 ms | 2.9 s | 6.2 s |

Per-patient queries are flat in collection size (indexed by patient and date). Collection-wide queries are linear.

Benchmarking caught a real defect: the first version of `care(group_by=…)` filtered the full encounter list once per
group, which is quadratic. It took 0.7 s at 500 synthetic patients and minutes at 10,000. It now buckets in one pass.

## Scaling to 500K–1M documents (estimates, derived from the measurements above)

**First bottleneck: LLM extraction** (`backbone/extract.py: extract_document`, fanned out by the thread pool in
`backbone/ingest.py`).

- At the measured $0.045 and 13 s per document, 1M documents ≈ **$45K list price** and **~22 days** at our measured
  0.53 documents/s.
- About 90% of input tokens are the fixed prompt + schema. Explicit prompt caching plus the **Batch API (−50%)**
  gives roughly **$15–22K**, with throughput bounded by rate limits rather than code.
- A cheaper extractor (Sonnet 5.5 at half the price; Haiku 5.5 at ~1/40) is the biggest lever. It should be adopted
  only if the agreement harness above shows it reproduces this corpus's reconciled results.
- The sha256 cache already makes re-runs and duplicate deliveries free.

**Next bottlenecks:**
- **Collection-wide compliance.** `project.weekly_compliance` issues one query per patient-week (6.2 s for 10K
  patients, measured). At ~32K patients (1M documents at this corpus's ratio) that is roughly 20 s per run.
  - Fix: persist a `patient_week` projection, rebuilt per patient on reconcile, and compute compliance and streaks
    as set-based SQL.
- **SQLite's single writer.** It becomes the write bottleneck once ingest is parallel across machines → Postgres.
  Reconciliation is already per patient (4 ms) and partitions cleanly behind a queue of "dirty" patient IDs.
- **Narration tokens.** The narrator receives full evidence JSON (13K–97K input tokens per answer, measured).
  - Fix: pass totals plus capped evidence, and let the narrator request more.

## AI and LLM usage (summary)

The LLM is used in exactly three runtime places:
1. **per-document extraction**, which records what each document asserts, with verified quotes;
2. **question → QueryPlan planning**;
3. **narrating** computed results.

Everything that decides a clinical number is deterministic: hashing, quote verification, reconciliation rules,
interval arithmetic, plan verdicts, SQL operators and the post-check. Extraction is the only AI step that feeds
numbers. It is guarded by code-verified quotes, value grounding (a service event's times and minutes must be in its
own quotes), interval-only extraction, cross-checks and golden tests.

Model choice, cost projections (for example, an estimated ~$15K with Opus or ~$7.7K with Sonnet for a 1M-document
batched backfill) and the risks are in **[`docs/AI_USAGE.md`](docs/AI_USAGE.md)**.

## Models, settings and assistance

- **Extraction:** `claude-opus-5-5`, effort `high`, one call per document, JSON-schema-constrained output
  (`claude -p --json-schema …`, tools disabled, no project settings loaded).
- **Planner and narrator:** `claude-opus-5-5`, effort `medium`, also schema-constrained.
- **Approximate model cost:** extraction $1.38; answers $0.08–0.62 each (list-price equivalents, measured).
- **AI assistance:** the architecture was discussed with ChatGPT (`INIT.md`). The implementation, tests and this
  README were written in pair-programming with **Claude Code (Claude Opus 5.5)**. Outputs are checked against the
  hand-derived expected values by the golden tests, and every narrative answer is post-checked against the computed
  results.

## Execution logs

- `out/answer_run.log` and `out/answer_unseen_run.log`: per-question timings and post-check status.
- `out/answers/*.json`: the full record for each question (plan, results with SQL, narrative, timings, token usage).
- The `run_log` table in `out/backbone.db`: CLI ingest/reconcile runs with durations and statistics.
- `out/benchmarks.json` and `out/benchmarks_synthetic_2000.json`: measured performance.
- `out/ablation.{md,json}`: the design-decision experiment.

## Repository layout

```
backbone/schema.py      extraction contract (Pydantic)        backbone/reconcile.py   rules R0–R9, decisions, conflicts
backbone/extract.py     prompt + cached per-document call     backbone/project.py     bounds, weeks, plan-in-effect, verdicts
backbone/llm.py         claude-cli | anthropic-api backends   backbone/query.py       QueryPlan DSL (Scope + 4 step types)
backbone/evidence.py    quote → verified line spans           backbone/operators.py   care, compliance, timeline, compare
backbone/ingest.py      hash, dedupe, extract, claims         backbone/dsl.py         fluent Python builder → QueryPlan
backbone/intervals.py   interval algebra                      backbone/answer.py      plan → execute → narrate → post-check
backbone/export.py      patient JSON + property graph         backbone/summary.py     compact `plan --summary` readout
backbone/paths.py       safe output file names                backbone/bench.py, ablation.py
cache/extractions/      shipped extraction cache              out/                    db, answers, abstraction, benchmarks
plans/                  hand-written QueryPlans (no LLM)      tests/                  rule unit tests + golden end-to-end tests
docs/index.html         human overview (built by docs/build_site.py)   AGENTS.md, CLAUDE.md, docs/agents/   agent guides
```
