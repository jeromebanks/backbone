# Clinician Q&A: natural-language questions → computed, cited answers

**Confidential:** part of a private submission (see `AGENTS.md`).
**Related:**
- [ROADMAP.md](ROADMAP.md) (Phase 3);
- [agents/QUERY_DSL.md](agents/QUERY_DSL.md) (today's DSL);
- the Claude Code skill [`.claude/skills/clinical-qa`](../.claude/skills/clinical-qa/SKILL.md), which is the
  single-user version of this design.

## 1. What exists today

| Piece | Today | Measured |
|---|---|---|
| Planner | LLM writes a `QueryPlan` (typed JSON DSL, Pydantic-validated) | 2.8–4.7 s |
| Executor | four deterministic operators over SQLite | 7–10 ms per question |
| Narrator | LLM writes a cited answer from the full results JSON | 15–49 s; 13K–97K input tokens |
| Verifier | post-check: numbers ∈ results, cited documents exist, line references backed by evidence passages | 11/11 saved answers pass |
| Cache | per question + whole-corpus fingerprint | 1.3 ms on a hit |
| Interfaces | `python -m backbone ask`, and the `clinical-qa` Claude Code skill (Claude Code is the planner and narrator; the CLI is the calculator) | |

**End to end: 20–52 s and $0.08–0.62 per new question (measured).** Narration dominates both. Execution is
essentially free. The design below keeps the architecture and attacks the latency, cost, concurrency and governance
gaps.

## 2. Requirements for the production version

- **Grounded:**
  - every number is computed by the engine;
  - every claim is cited to a verified passage;
  - uncertainty is shown as ranges and UNDETERMINED, never hidden.
- **Conversational:** follow-ups ("what about the week before?", "only group sessions"), clarifying questions when
  the patient or period is ambiguous, and patient context taken from the reviewer's screen.
- **Fast:**
  - first tokens in under 2 s;
  - full answer p95 under 10 s for per-patient questions;
  - collection-wide questions run as async jobs when they are expensive.
- **Safe:**
  - PHI isolation per tenant, with RBAC on patients;
  - no clinical advice beyond what the record documents;
  - document text is treated as untrusted data (prompt injection).
- **Auditable:** every exchange is stored with its plan, versions, results hash, answer and viewer, and can be
  re-verified later (`verify-answers` at scale).
- **Measurable:** offline evals gate changes; online metrics catch drift.

## 3. Architecture

```
Reviewer UI (patient workspace + chat panel, "show calculation", evidence drawer)
   │  question + context {tenant, user, patient in view, date range in view, conversation id}
   ▼
QA Gateway (FastAPI) ── authN/Z (OIDC, RBAC: may this user see these patients?) ── rate limits per tenant/user
   │
   ▼
Conversation service ── session state: prior plans, resolved patient/period, clarifications (Postgres/Redis)
   │
   ▼
Intent router ──► fast path: template intents (≈ most traffic) → parameter extraction → QueryPlan  (no planner call)
   │         └──► planner (LLM, tool-use or structured output) → QueryPlan ─┐
   │                     ▲ few-shot: similar past (question → plan) pairs    │
   │                     ▲ directory slice: only patients the user may see  │
   ▼                                                                         ▼
Plan validator ── schema + semantic checks (dates in episode? patients allowed? cost estimate) ── clarify / refuse / async
   │
   ▼
Executor ── per-patient operators on Postgres projections (ms) │ collection-wide on the analytics store (s) │ async jobs
   │          plan-result cache keyed by (normalized plan, versions, patient watermarks)
   ▼
Answer composer
   ├─ deterministic templates for numeric intents (tables, ranges, calculations, exclusions): no LLM
   └─ narrator LLM (streaming) for explanatory/qualitative parts, given a COMPACT results digest
   ▼
Verifier ── post-check (numbers, document IDs, line refs); faithfulness checks on sampled answers;
   │        on failure: one regeneration, then fall back to the template answer plus raw results
   ▼
Response ── streamed answer · "how this was computed" (plan, calculations, SQL) · evidence drawer · feedback buttons
   │
   ▼
Audit + analytics ── qa_exchanges (question, plan, versions, results hash, answer, post-check, user, latency, cost)
                 └── feedback → eval set (question→plan gold pairs; answer corrections)
```

### 3.1 Key design choices

1. **The DSL stays the contract between language and computation.** Both the template router and the LLM planner
   emit the same `QueryPlan`. The planner can use **tool use** (one tool per operator with a strict schema) or
   structured output. Either way, nothing reaches the database except a validated plan.
2. **A template fast path for common intents.** Most reviewer questions fall into a few intents: totals, weekly
   compliance, day reconstruction, exclusions, assessments over time, before/after. These can be classified and
   parameterised cheaply (a small model or rules plus the UI context) and both planned and narrated by template,
   with no large-model call. That gives sub-second answers and near-zero cost, and the LLM is reserved for novel
   phrasing and explanation.
3. **Compact results for the narrator.** Today the narrator receives the full results JSON. Production sends a digest
   (totals, groups, conflicts, exclusions, decisions, and the top cited passages); this is what `backbone.summary`
   already produces. The full evidence remains one click away in the UI. *Estimate:* 13K–97K tokens → about 3–8K,
   with proportionally lower narration latency and cost.
4. **Streaming and a split response.** The deterministic part (direct answer, table, calculation) renders
   immediately from results. The narrative streams in after it. The clinician sees verified numbers first.
5. **Verification is a gate, not a log.** A post-check failure triggers one regeneration with the failures fed back.
   If it fails again, the response falls back to the template answer. A wrong number is never shown silently.
6. **Three answer tiers, always labelled:**
   - **Computed:** operators answered the question.
   - **Retrieved, not computed:** the question is outside the operators, so quoted passages are returned from
     pgvector search over *verified* claims and observations for the patients in scope. Nothing is counted.
   - **Unsupported:** what the system can't do, with a suggestion.
7. **Conversation state is plan state.** A follow-up is answered by *editing the previous plan* (narrow the scope,
   add a step, change `group_by`), not by re-planning from scratch. This is cheaper, consistent, and easy to explain:
   "same as before, but only group therapy".
8. **Scope from context and permissions.** The planner only sees directory entries for patients the user may access.
   The patient and date range in view are defaults. The validator rejects plans that reference unauthorised patients.
9. **Collection-wide questions are jobs.** The validator estimates cost from the scope (patients × weeks). Cheap
   questions run inline against the analytics store. Expensive ones become async jobs with a notification. Results
   are snapshotted by projection version.

## 4. Scalability and performance

| Concern | Choke point | Design response |
|---|---|---|
| Latency | narration 15–49 s (measured) | streaming, compact digest, deterministic template for the numeric part, a smaller narrator model where the eval shows parity |
| LLM cost per question | $0.08–0.62 (measured) | template fast path, digest, plan and result caches, model routing (estimate: under $0.02 average per question with most traffic templated) |
| Cache hit rate | today's fingerprint is invalidated by **any** new document | key on (normalized plan, versions, watermarks of the patients in scope); plan caching by normalized question embedding plus intent |
| Concurrency | single process today | stateless gateway, planner, executor and composer; horizontal autoscaling; per-tenant LLM token buckets |
| Collection-wide queries | 6.2 s at 10K patients, linear (measured, synthetic) | materialized `patient_week` + set-based SQL in the analytics store; async jobs above a cost threshold |
| Planner errors | free-form questions → wrong plan | intent templates first; few-shot retrieval of verified question → plan pairs; plan validator with clarifications; a question → plan gold set in CI |
| Prompt injection | document text reaches the narrator through quotes | quotes are passed as delimited data; system instructions forbid following them; structured outputs; the post-check; no tool access in narration |

## 5. DSL roadmap

The DSL works for the prototype's questions. Production needs it to grow without becoming a general query language.
In priority order:

1. **Versioned schema.** Add `dsl_version` on every plan, with migrations for stored plans. Old answers stay
   re-executable.
2. **Richer scope and filters:**
   - `episode` as a first-class scope;
   - relative periods ("last 4 weeks", "episode week 2"), resolved by the validator;
   - provider and site filters;
   - `exclude_encounters` and `only_disposition` filters.
3. **New operators, each with golden tests and planner docs:**
   - `authorization`: authorized vs scheduled vs attended units;
   - `documentation_gaps`: encounters with conflicts, missing signatures, uncertain attendance, or charges without
     attendance;
   - `providers`: care by clinician or role;
   - `assessment_change`: score deltas with ranges and instrument-specific thresholds, reported as documented and
     not interpreted clinically;
   - `cohort`: patient sets defined by a compliance or assessment predicate, for collection-wide follow-ups.
4. **Composition.** A step may reference a previous step's output set (e.g. `compliance` → the patients with
   `definite` runs → `care` for those patients). This replaces "free-form joins" with named, typed references.
5. **Plan normalization and canonical form.** Order-independent arguments, resolved dates, default elision. This
   makes plan caching, deduplication, and question → plan evals exact.
6. **Explain and cost.** `plan.explain()` in clinician language ("weekly goal check for Rowan, Jan 5–30, two-week
   streaks"). `plan.estimate()` (patients × weeks, collection vs patient) drives the inline-vs-async choice.
7. **Python and SQL parity.**
   - The fluent DSL covers every operator and argument.
   - Operators compile their aggregation to set-based SQL for collection scope.
   - Per-patient execution keeps the Python projection, so semantics stay identical; parity tests compare the two
     paths on synthetic cohorts.
8. **Permissions in the plan.** The validator stamps the authorised patient set onto the plan, and execution
   enforces it (defence in depth beyond row-level security).
9. **Retrieved-tier operator.** `evidence_search(scope, query)` returns ranked verified passages and is explicitly
   non-computing. It is the only place embeddings enter.

## 6. Evaluation and monitoring

**Offline, gating every prompt, model or DSL change:**
- **Question → plan gold set:** paraphrase families per intent. Metric: exact canonical-plan match, or a
  results-equivalent plan.
- **Answer quality:** post-check pass rate; numeric accuracy against gold; citation validity; faithfulness (LLM
  judge plus clinician review on samples); correct handling of uncertainty (UNDETERMINED must not be "resolved").
- **Safety set:** out-of-scope clinical-advice requests, cross-patient access attempts, injection strings embedded
  in documents.

**Online:**
- post-check failure and regeneration rates; template vs planner share; clarification rate; unsupported rate;
- p50/p95 latency per stage; cost per question; cache hit rates;
- thumbs and corrections → triage → the eval set.

## 7. Phasing

| Phase | Build | Exit criteria |
|---|---|---|
| A (2 wks) | QA API wrapping today's pipeline; auth and RBAC; audit table; digest-based narration; streaming; scoped cache keys | p95 < 15 s; post-check gate enforced; 100% of exchanges auditable |
| B (3 wks) | intent router + templates for the top intents; conversation state as plan edits; clarifications | ≥ 60% of traffic templated; template p95 < 1.5 s; question → plan gold accuracy ≥ 95% |
| C (3 wks) | DSL v2 (episode scope, relative periods, composition, new operators); plan normalization; plan cache | new operators with golden tests; parity tests green |
| D (3 wks) | collection-wide on the analytics store plus async jobs; retrieved-tier `evidence_search` (pgvector); safety eval set | collection p95 < 10 s inline or async; safety set 100% pass |
| E (ongoing) | eval dashboards, feedback loop, model routing for planner and narrator | cost per question and quality tracked per release |

## 8. The Claude Code skill as the first client

The `clinical-qa` skill already runs the whole loop: directory → plan → execute → answer → post-check. Claude Code
is the planner and narrator; the repository's CLI is the deterministic engine. It is useful today for reviewers
and developers working in the repo, and the production service is the same contract at scale:

| Skill (single user, local) | Production service |
|---|---|
| `python -m backbone directory` | directory slice filtered by RBAC |
| Claude writes the QueryPlan JSON | intent templates, or the planner LLM |
| `python -m backbone plan --summary --out` | executor + digest |
| Claude writes the answer | template composer + streaming narrator |
| `python -m backbone postcheck` | verifier gate with regeneration and fallback |
| `/tmp` scratch files | `qa_exchanges` audit table |
