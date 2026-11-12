# AI and LLM usage

**Confidential:** part of a private submission (see `AGENTS.md`).

**In one sentence:** the language model reads documents and talks to people; everything that decides a clinical
number is deterministic code.

**Measured vs estimated.** "Measured" figures come from this repository's runs (`cache/extractions/*.json`,
`out/answers/*.json`, `out/benchmarks.json`). Cost figures are **API list-price equivalents** reported by the Claude
CLI: the prototype ran on a Claude subscription, so no API bill was actually incurred. Prices are Claude list
prices per million tokens as of November 2026; re-check them before quoting.

---

## 1. Where AI is used, and where it isn't

| # | Stage | AI? | Model and settings (prototype) | What the AI decides | What it may NOT decide |
|---|---|---|---|---|---|
| 1 | Ingest: hashing, dedupe, Document ID from header | **No** | n/a | n/a | n/a |
| 2 | **Extraction** (`extract.py`): one call per document | **Yes (LLM)** | Claude Opus 5.5, effort `high`, JSON-schema output, tools disabled | What each document *asserts*: intervals, dispositions, signatures, corrections and copies, assessments, observations, plan requirements, plus verbatim quotes | Durations, arithmetic, conflict resolution, cross-document links by ID, which record wins |
| 3 | Quote verification (`evidence.py`) | **No** | n/a (difflib fuzzy fallback, deterministic) | n/a | n/a |
| 4 | Claims and patient attribution (`ingest.build_claims`) | **No**, but it consumes LLM output | n/a | n/a | n/a |
| 5 | **Reconciliation** (`reconcile.py`, rules R0–R9) | **No** | n/a | n/a | n/a |
| 6 | Interval arithmetic, projection, plan verdicts (`intervals.py`, `project.py`) | **No** | n/a | n/a | n/a |
| 7 | Operators + SQL (`operators.py`, `query.py`) | **No** | n/a | n/a | n/a |
| 8 | **Planner** (`answer.py`): question → QueryPlan | **Yes (LLM)** | Claude Opus 5.5, effort `medium`, schema-constrained | Which operations, scope and parameters answer the question | Writing SQL or code, computing anything (it emits a validated plan only) |
| 9 | **Narrator** (`answer.py`): results → cited answer | **Yes (LLM)** | Claude Opus 5.5, effort `medium`, schema-constrained | Wording, structure, and which computed facts and citations to present | New numbers, new arithmetic, uncited claims (enforced by the post-check) |
| 10 | Post-check (`answer.postcheck`) | **No** | n/a | n/a | n/a |
| 11 | Caches, `verify-answers`, export, benchmarks, ablation, HTML docs | **No** | n/a | n/a | n/a |
| 12 | **`clinical-qa` Claude Code skill** | **Yes**: Claude Code itself plans and narrates | The user's Claude Code session | Same roles as 8 and 9 | Same limits. Numbers come from `python -m backbone plan`; answers must pass `python -m backbone postcheck` |

**Development-time AI (not part of the runtime):**
- the architecture was discussed with ChatGPT (`INIT.md`);
- the code, tests and docs were written in pair-programming with Claude Code (Claude Opus 5.5).

### Where AI output can still affect a result

1. **Extraction is the only AI step that feeds numbers.** A misread time or disposition flows into reconciliation.
   Mitigations:
   - verbatim quotes are verified in code (R0; 0 unverified of 254 claims, measured);
   - intervals are recorded, never minutes;
   - relationships are keyed on IDs the text states;
   - stated totals are cross-checked against computed ones (this caught D113's "45 min" vs 30 patient-present
     minutes);
   - the golden tests and the ablation.

   **Residual risk:** a plausible but wrong value that *is* quoted correctly. Example: a correct quote attached to
   the wrong field. The gold-set eval and agreement harness (ROADMAP Phase 1) are the next defence.
2. **Patient attribution depends on the extracted MRN** (`ingest.py`). A misread MRN would attribute a document to the
   wrong patient. In production this moves to a patient-matching service with review queues (ROADMAP §3.1 item 5).
3. **The planner can answer the wrong question correctly.** A valid plan with the wrong scope gives right numbers
   for the wrong question. Mitigations: the plan is shown with every answer ("How this was computed"); a
   question → plan gold set; templates for common intents (CLINICAL_QA_DESIGN §3.1).
4. **The narrator can misphrase.** The post-check enforces that numbers come from the results, documents exist, and
   line references are backed by evidence. Prose interpretation is not machine-checked; the narrator is instructed
   to separate fact from interpretation, and this is sampled for clinician review in production.

### Determinism and reproducibility

- LLM outputs can differ between runs. Two caches freeze them:
  - the **extraction cache** (per document hash, extractor version and model);
  - the **answer cache** (per question and abstraction fingerprint).
- Everything downstream of the extraction cache is deterministic and byte-reproducible. Rebuilding from the cache
  makes 0 LLM calls, and `python -m backbone verify-answers` re-executes every saved plan and requires identical
  results.
- Re-running extraction is treated as a new extractor run, not a correction. Its effect is measured by diffing
  reconciled outcomes.

---

## 2. Usage and cost: measured

| What | Measured |
|---|---|
| Extraction, 31 documents | **$1.38 total**, **$0.045/doc**; 8,318 input + 1,574 output tokens per doc (≈90% of input is the fixed prompt + schema); 13.2 s mean per doc; 58 s wall clock at concurrency 8 |
| Answering, 11 saved questions (planner + narrator) | **$2.06 total**; $0.08–0.62 per development question; $0.01 for a refused (unsupported) question; 3.6K–97K input tokens per question |
| Planner latency | 2.5–5.8 s |
| Narrator latency | 14–49 s; **dominates** answer time and cost |
| Execution (no AI) | 7–10 ms per question; 0.2–1.7 ms per operator |
| Repeated question (cache) | ~1.3 ms, $0 |
| Whole development effort (estimate) | about $10–20 list-equivalent: one extraction pass plus several regenerations of the answer set |

---

## 3. Model choice: considerations per role

| Role | What matters most | Volume | Recommendation |
|---|---|---|---|
| **Extraction** | Field-level accuracy on critical fields (dates, intervals, disposition, presence, corrections and copies); faithful quoting; following the schema | **Highest**: one call per document, ~1M for a backfill | Start on Opus. Build the gold set (200–500 docs). Then route by document type: try Sonnet 5.5, and Haiku 5.5 for simple, structured types (rosters, schedule exports, notices), keeping each only where reconciled outcomes match Opus. Use Opus (or higher effort) as the fallback for low-confidence or long documents. |
| **Planner** | Mapping language to the right operators, scope and dates; schema adherence | One per new question; small outputs | Sonnet- or Haiku-class plus a **template fast path** for common intents (no model call). Validate on a question → plan gold set. |
| **Narrator** | Faithfulness to results, citations, clear handling of uncertainty | One per new question; **today's biggest cost and latency** | Sonnet-class with a **compact results digest** and streaming. A deterministic template renders the numeric part, so the model only writes the explanation. |
| **Embeddings** (future "retrieved, not computed" tier) | Recall over verified passages; BAA coverage | Per claim, once | pgvector in Postgres; embedding model under the same BAA |

**Cross-cutting considerations:**
- **Compliance.** Production needs a **BAA** (business associate agreement) covering PHI for every model provider
  (Anthropic API, or Claude via a cloud provider). Check data-retention and residency terms per model. A personal
  Claude subscription (used for this prototype) is **not** a production path.
- **Effort is a lever as well as model choice.** Extraction ran at `high`; `medium` may hold accuracy on simple
  document types. Measure it on the gold set, and tune per document type.
- **Pin model versions and gate changes.** Provider updates can shift extraction. Pin versions; shadow-run on a
  sample; promote only if the eval holds (INGESTION_PIPELINE §6).
- **Refusals.** Clinical text includes self-harm language. Safety classifiers may occasionally decline a document.
  The pipeline must treat a refusal as a retriable failure with a model fallback and a dead-letter state, never a
  silent drop (the `anthropic-api` backend enables server-side fallbacks; the CLI path retries).
- **Rate limits, not compute, are the throughput ceiling.** Plan the per-tenant token-per-minute budgets and Batch
  quotas.
- **Prompt injection.** Document text reaches the narrator as quoted data. Keep it delimited; never give the
  narrator tools; rely on the post-check gate.
- **Lock-in.** The LLM sits behind `llm.complete_json` with schema validation. Switching models or providers changes
  one module, but every switch must pass the same evals.

---

## 4. Cost projections (estimates)

**Formula** (same as the estimator in `docs/ingestion.html`):

```
cost per document = input_tokens × [(1 − cached_share) × price_in + cached_share × price_in × cache_read_rate]
                  + output_tokens × price_out          (÷ 2 with the Batch API)
```

**Assumptions:**
- the measured 8,318 input and 1,574 output tokens per document;
- 90% of the prompt prefix cached;
- cache reads at 5% of the input price (10% assumed for Haiku);
- 15% of documents skipped as non-clinical or near-duplicates.

**Extraction:**

| Model (list $/MTok in/out) | Per doc, real-time, cached | Per doc, Batch | 1M-document backfill (850K extracted), Batch | Daily feed, 5K docs/day, Batch |
|---|---|---|---|---|
| Opus 5.5 ($4 / $20) | $0.036 | $0.018 | **~$15.4K** (real-time: ~$30.9K) | ~$77/day |
| Sonnet 5.5 ($2 / $10) | $0.018 | $0.009 | **~$7.7K** | ~$39/day |
| Haiku 5.5 ($0.10 / $0.50) | $0.0009 | $0.0005 | **~$0.4K** | ~$2/day |
| *Measured baseline (Opus, real-time, CLI)* | *$0.045* | | | |

A realistic production mix routes most structured documents to a cheaper model and keeps clinical notes on a
stronger one. That lands between the Sonnet and Opus rows: **roughly $5–15K per 1M documents** (estimate), with the
gold-set eval deciding the mix.

**Question answering:**
- **Today:** $0.08–0.62 per new development question (measured).
- **Target:** templates for common intents with no model call, a compact digest for the narrator (an estimated
  13K–97K → 3–8K input tokens), and a Sonnet-class narrator. That gives an estimated **< $0.02 average per new
  question**. Repeats cost $0 from the cache.

**What doesn't cost model money:**
- reconciliation (~4 ms per patient);
- rule changes (re-reconcile only);
- rebuilds from the cache;
- every deterministic query.

The expensive events are new documents, **extractor or model changes** (re-extraction, so limit them to the affected
document types), and new narrated answers.

**Cost controls to build in:**
- per-tenant budgets and alerts;
- cost-per-document and cost-per-question dashboards by model and lane;
- `max_tokens` caps;
- batch-by-default for anything not interactive;
- caching at every layer;
- one combined extractor version bump for new fields (CLINICAL_QA_DESIGN §5C).
