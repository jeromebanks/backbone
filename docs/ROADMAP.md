# Roadmap: from prototype to production

**Confidential.** This is part of a private submission; see `AGENTS.md`.

This document describes what it takes to turn the prototype into a production clinical-review system. It proposes
a tech stack and a system design, and it lists the scalability choke points: where they are in today's code, how bad
they are (measured where possible), and how to remove them.

**Measured vs estimated.** Figures marked *measured* come from `out/benchmarks.json` (31 real documents; synthetic
query-layer scale up to 10K patients). Everything else is an estimate and is labelled as one.

---

## 1. Production assumptions

The problem statement implies these assumptions:

- **Volume:** 500K–1M+ documents initially, plus new documents every day. The steady-state volume is unknown; this
  plan assumes **2–10K documents a day** (estimate). Many patients and episodes, and **repeated reviews** of the same
  patients.
- **Users:** clinical reviewers who need to trace every conclusion to source passages, plus collection-wide analytics
  ("which patients had two consecutive weeks below their requirements").
- **Data:** real PHI (protected health information) instead of synthetic records. That means HIPAA (the US health
  privacy law), BAAs (business associate agreements) with every vendor that handles PHI, audit logs, retention
  rules, and least-privilege access. Data likely belongs to multiple client organisations (tenants).
- **Inputs:** PDFs, scans and faxes, EHR exports (exports from electronic health record systems), HL7 and FHIR (the
  standard health-data interchange formats), and CSV extracts, not just clean `.txt` files. Some documents cover
  **several patients**: group rosters, schedule exports, billing batches.

## 2. What carries over from the prototype, and what doesn't

| Keep (it's the product's core) | Replace or extend |
|---|---|
| Claims ≠ facts: an append-only evidence layer, with the clinical layer derived from it | SQLite → Postgres; filesystem → object storage + events |
| Extracting intervals, never minutes; interval algebra in code | One-shot ingest CLI → durable, queue-driven workflows |
| Precedence by relationship (corrections, copies, tiers), never by date | One patient per document → claims carry their own patient |
| `[low, high]` bounds and MET / NOT_MET / UNDETERMINED | The answer-cache fingerprint covers the whole corpus → scope it to the patients a question touches |
| Code-verified quotes and line spans | `.txt` only → normalisation pipeline (PDF, OCR, HL7/FHIR) |
| Versioned extractor, rules and queries; content-hash extraction cache | Per-query projection → a materialised `patient_week` |
| A typed `QueryPlan` over shared projection semantics; the LLM never writes SQL | Single-pass extraction → evaluated, model-routed, batched extraction |
| Golden tests, `verify-answers`, ablation | One hand-labelled patient → a labelled gold set and continuous evaluation |

---

## 3. Target system design

```
                ┌─────────────────────────── control plane: Temporal (durable workflows, retries, backfills) ─────────────────────────┐
 sources        │                                                                                                                      │
 EHR/SFTP/API ─►│ Intake API ─► Object store (S3, content-addressed by sha256, KMS-encrypted, immutable)                               │
 fax/PDF/HL7    │      │                                                                                                              │
                │      ▼ event: document.received {tenant, sha256}                                                                    │
                │ Normalise (PDF text / OCR / HL7→text, page+line map) ─► document.normalized                                         │
                │      ▼                                                                                                              │
                │ Classify + route (cheap model or rules: type, patients mentioned, skip/dup) ─► Extraction lanes:                    │
                │      • interactive lane: real-time Claude API, prompt-cached   (patient under active review, < 2 min)               │
                │      • bulk lane: Message Batches API, prompt-cached           (backfill/daily feed, ≤ 24 h, −50% cost)             │
                │      ▼                                                                                                              │
                │ Verify quotes → claims (Postgres, partitioned by tenant + patient hash) ─► patient.dirty {tenant, patient, episode} │
                │      ▼                                                                                                              │
                │ Reconcile workers (pure, idempotent, versioned rules; one patient-episode per job; ms each)                         │
                │      ▼                                                                                                              │
                │ Clinical tables + decisions + conflicts ─► materialised projections (patient_week, episode summary)                 │
                │      ▼ CDC (change data capture)                                                                                    │
                │ Analytics store (warehouse / ClickHouse / DuckDB-on-Parquet) for collection-wide questions                         │
                └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 consumers:
   Query API (FastAPI): QueryPlan → operators → envelope   ← Planner/Narrator service (LLM)   ← plan cache, answer cache scoped to patients
   Reviewer UI: timeline, evidence, conflicts; adjudications are written back as claims with the highest tier
   Ops: OpenTelemetry traces, cost/token dashboards, eval dashboards, audit log
```

The ingestion half of this diagram is specified in detail in **[INGESTION_PIPELINE.md](INGESTION_PIPELINE.md)**
(stage contracts, idempotency keys, lanes, coalescing, backfills, testing, rollout) and drawn in
[`ingestion.html`](ingestion.html).

### 3.1 Key design decisions

1. **Postgres is the system of record. Object storage holds the bytes.**
   - Documents are immutable objects keyed by sha256 (deduplication and integrity come for free).
   - Claims, the clinical layer, decisions and projections live in Postgres, using JSONB for variable payloads and
     typed columns for anything filtered or aggregated (as in the prototype).
   - Partition by `tenant_id` and hash(patient). This keeps per-patient work local and allows row-level security
     per tenant.
2. **Event-driven and incremental at every hop.** Each stage consumes an event and emits one. The "dirty
   patient-episode" set replaces "reconcile everything", so a new document costs one extraction plus a few
   milliseconds of reconciliation, never a rescan.
3. **Temporal for orchestration.** LLM calls are slow, rate-limited and occasionally refused. Temporal (or Step
   Functions, if we stay AWS-native) gives durable retries, backoff, timeouts and resumable backfills, without
   hand-rolled queue bookkeeping. Workers stay plain Python.
4. **Two extraction lanes.** Real-time API calls are used when a reviewer is waiting; the Batch API is used for
   backfills and nightly feeds. Both share one extraction contract, cache and version.
5. **Claims carry their own patient.** Today the document carries the MRN (`ingest.py`). Production extraction emits
   `patient_ref` per event or assessment, resolved through a **patient-matching service**: a master patient index,
   or deterministic rules on MRN, name and DOB plus review queues for ambiguous matches. Multi-patient documents then
   fan out to the right patients.
6. **An episode is a first-class entity.** The prototype assumes one episode. Production keys reconciliation and
   projections on (tenant, patient, episode). Episode boundaries come from plans, admissions and authorisations.
7. **Bitemporal records.** Every claim and decision records *valid time* (when the care happened) and *recorded time*
   (when we learned it). That makes it possible to ask "what did we conclude as of the Jan 20 review?", which matters
   for audits and for explaining why an answer changed.
8. **Human adjudication is evidence.** When a reviewer resolves a conflict (for example, E115: 40 vs 50 min), the
   resolution is written back as a claim in the highest evidence tier, with author, rationale and timestamp. It is
   never an edit to derived tables. It then survives every re-reconciliation automatically.
9. **Versioned everything, with safe rollouts.**
   - A rules change re-reconciles affected patients in the background. It is cheap (milliseconds per patient) and
     needs no LLM.
   - An extractor change runs in **shadow mode** on a sample first. It is promoted only if the field-level eval
     holds, and then re-extracts only the affected document types.
   - Projections record the rule version and extractor version they were built from.
10. **Answers are scoped and reproducible.** The cache key becomes (normalised plan, versions, hashes of the patients
    in scope), not the whole corpus. The stored answer keeps its plan, results, SQL and evidence, as
    `out/answers/*.json` does today.

---

## 4. Proposed tech stack

| Concern | Choice | Why / alternatives |
|---|---|---|
| Language and services | **Python 3.12, FastAPI, Pydantic v2** | Reuses all prototype code and the typed contracts |
| System of record | **PostgreSQL 16** (Aurora or Cloud SQL), JSONB, declarative partitioning, row-level security | Transactions, joins, partial indexes, mature ops. SQLite stays for tests and offline bundles |
| Document storage | **S3** (or GCS) with SSE-KMS, object lock, lifecycle rules | Immutable, content-addressed bytes; cheap |
| Normalisation | PDF text extraction (pdfplumber or PyMuPDF) + **OCR** (AWS Textract or Google Document AI) + HL7/FHIR parsers | Keeps page and line maps so evidence spans still resolve |
| Orchestration | **Temporal** (Cloud or self-hosted) | Durable LLM workflows, retries, backfills, visibility. Alternatives: AWS Step Functions, or Celery for a smaller team |
| Events | **SQS/SNS** (or Kafka/MSK if replay and many consumers matter) | Fan-out from intake to the stages |
| LLM | **Anthropic API** (Claude) under a BAA, or Claude on Amazon Bedrock; **structured outputs, prompt caching, Message Batches**; model routing (Opus for hard documents, Sonnet or Haiku where the eval shows parity) | The prototype already runs on Claude. Batches give −50%; caching covers the ~90% fixed prefix |
| Analytics | Postgres materialised projections + a CDC feed (change data capture) into **ClickHouse or Snowflake/BigQuery** (or DuckDB over Parquet at smaller scale) | Collection-wide queries off the OLTP path |
| Cache | Redis (plan and answer caches, rate-limit tokens) | Scoped keys; invalidation driven by patient dirtiness |
| Reviewer UI | React/TypeScript SPA (the prototype's `docs/index.html` timeline and evidence panel is the starting design) | |
| AuthN/Z | OIDC SSO (Okta or Azure AD), RBAC per tenant, Postgres RLS | PHI least privilege |
| Observability | OpenTelemetry → Datadog or Grafana; LLM token and cost metrics per stage, tenant and model | Cost is the main operational metric |
| Evaluation | Gold-set harness in CI (field-level extraction F1, reconciliation golden tests, answer post-check rate); dashboards | Gates every extractor or model change |
| Infra and CI | Terraform; EKS or ECS Fargate; GitHub Actions; container scanning | |
| Security and compliance | KMS everywhere, VPC endpoints, no PHI in logs, audit log table and stream, retention jobs, HIPAA BAA inventory, SOC 2 controls | |

---

## 5. Scalability choke points

Ordered by when they bite. "Where" points at today's code.

| # | Choke point | Where (prototype) | Evidence | Production fix |
|---|---|---|---|---|
| 1 | **LLM extraction throughput, cost and rate limits**: the first bottleneck | `extract.py:extract_document` via the `ThreadPoolExecutor` in `ingest.py` | *Measured:* 13.2 s/doc, 8.3K input + 1.6K output tokens, $0.045/doc list, 0.53 docs/s at concurrency 8. *Estimate:* 1M docs ≈ 10B tokens ≈ $45K list price and ~22 days at that rate | **Batch API** (−50%; throughput set by batch quota, not our threads). **Prompt caching** of the fixed prompt + schema (~90% of input). **Model routing** by eval (Sonnet 5.5 ≈ ½ price; Haiku 5.5 ≈ 1/40 where accuracy holds). A cheap classifier skips documents with no clinical events and deduplicates near-copies. Concurrency is sized to tokens-per-minute limits per key/region. *Estimate:* $8–20K for a 1M backfill, depending on the model mix |
| 2 | **Re-extraction when the prompt or schema changes** (the whole corpus is invalidated) | `EXTRACTOR_VERSION` invalidates every cache entry | *Estimate:* the full cost of #1 again | Field-additive schema changes extract only the new fields. Shadow-evaluate on a sample; re-extract only affected document types; keep old extractions for reproducibility |
| 3 | **Answer cache invalidated by any new document anywhere** | `answer.py:fingerprint()` hashes **all** document sha256s | With daily arrivals the hit rate is ~0% after every feed. Each miss is 20–52 s and $0.08–0.62 (*measured*) | Key on (normalised plan, versions, `max(recorded_time)` of the patients in scope). Collection-wide answers are keyed on a projection snapshot ID |
| 4 | **Ingest rescans and rehashes the whole input directory** | `ingest.discover()` + `f.read_bytes()` on every file, every run | Fine at 31 docs. At 1M docs every incremental ingest reads the whole corpus (*estimate:* tens of GB of I/O) | Event-driven intake: hash once at upload; S3 events → queue; no scans |
| 5 | **One patient per document** | `ingest.py` sets `documents.patient_mrn` from the document header; claims inherit it | A multi-patient group roster would be attributed to one patient, or `UNRESOLVED` | Per-claim `patient_ref` + a patient-matching service; reconciliation fans out to every patient touched |
| 6 | **Collection-wide compliance queries** (N+1 per patient-week) | `project.weekly_compliance` issues a SQL query per patient-week | *Measured:* 0.93 s at 2K patients and 6.2 s at 10K (linear). *Estimate:* ~20 s at 32K and minutes at 300K | Materialised `patient_week` rows maintained on reconcile. Compliance and streak detection as one set-based SQL (window functions) or in the warehouse. Per-patient queries are already flat (0.4–0.7 ms *measured*) |
| 7 | **Collection-wide `care` aggregation in Python** | `operators.care` → `project.aggregate` over every encounter row | *Measured:* 2.9 s for 260K encounters (after removing an O(groups × n) bug the benchmark exposed) | Push aggregation into SQL (`GROUP BY` over the projection); keep the bounds semantics by summing `low` and `high` columns |
| 8 | **The SQLite single writer** | `db.py` | Not measured under concurrency; the ceiling is structural | Postgres with pooling (PgBouncer); workers write per partition |
| 9 | **Narration latency and tokens** | `answer.py` sends the full evidence JSON to the narrator | *Measured:* 13K–97K input tokens; narration is 15–49 s of the 20–52 s total | Compact the results (totals, conflicts and top evidence; evidence fetched on demand). Stream the answer. Template the answer for common question types; use a smaller narrator model where the eval allows |
| 10 | **Per-encounter evidence lookups (N+1)** | `operators._docs_of` / `_evidence`, called per encounter | Fine per patient (*measured* 0.8 ms); grows with detail rows | Batch the lookups per query; denormalise `records` onto encounter rows at reconcile time |
| 11 | **Fuzzy quote matching on long documents** | `evidence.DocumentIndex.locate`: difflib sliding window, O(document × quote) | 0 fuzzy matches in this corpus, but a 100-page PDF would be slow | Exact and normalised search first (as today), then `rapidfuzz` over line-bounded candidates; cap the work and mark the span `unverified` instead of searching exhaustively |
| 12 | **Very long documents and very large patients** | One extraction call per document; `reconcile._group_events` matching is O(unidentified × groups) | Not hit here | Chunk documents by section/page and stitch events by encounter ID. Partition reconciliation by episode; index candidate matching by (date, type) |
| 13 | **Extraction errors are silent until someone looks** | Single pass; no confidence | The `U-` contacts in this corpus (see the README limitation) | A field-level eval gold set in CI; spot-check sampling; disagreement checks (k-run agreement on low-confidence fields) |
| 14 | **Hot tenants and backfills starving interactive work** | n/a | Bound to happen in production | Separate queues and rate-limit budgets per lane and tenant; Temporal task-queue priorities |

**Steady-state cost estimate** (assumptions, not measurements): 5K new documents a day × $0.045 ≈ $225/day at
Opus list price on the real-time lane. On the batch lane with caching and routing it is likely $60–120/day.
Answering 1K questions a day at the measured $0.08–0.62 ≈ $80–620/day, which plan and answer caching reduce
sharply.

---

## 6. Phased roadmap

Durations are for a small team (2–3 engineers plus clinical SME time) and are estimates.

### Phase 0: Foundations (2 weeks)
- Confirm the LLM provider and **BAA**, the data-residency and retention rules, and the tenancy model.
- Containerise; CI (lint, type-check, the existing test suite, `verify-answers`); Terraform skeleton; secrets in KMS.
- Port the schema to Postgres (Alembic migrations): add `tenant_id`, `episode_id`, per-claim `patient_ref`,
  bitemporal columns, and an audit-log table. Keep SQLite as the test backend behind a thin repository layer.
- **Exit:** the prototype's golden results reproduce on Postgres in CI.

### Phase 1: Production ingestion and extraction (4–6 weeks)
- S3 intake, document events, a normalisation service (PDF, OCR, HL7/FHIR) that preserves page and line maps.
- Temporal workflows for extraction with real-time and batch lanes, prompt caching, model routing and refusal fallbacks.
- **Gold set:** 200–500 documents labelled field by field across document types and sites, with an extraction-eval
  harness. Choose the cheapest model mix that matches Opus on reconciled outcomes.
- Multi-patient documents and patient matching (plus a review queue for ambiguous matches).
- **Exit:** a 50K-document backfill completes within budget; field-level F1 at or above the target; cost and latency dashboards live.

### Phase 2: Reconciliation and projections at scale (4 weeks)
- Dirty-set reconcile workers per (tenant, patient, episode); idempotent; ruleset versioning with background re-reconciliation.
- A materialised `patient_week` and episode summaries; set-based compliance and streak queries; CDC to the analytics store.
- Episode detection; plan-revision semantics (already designed and tested in the prototype).
- Reviewer adjudication written back as top-tier claims; "as-of" queries over the bitemporal data.
- **Exit:** a new document becomes queryable in under 5 minutes (real-time lane); collection-wide compliance over
  1M documents in under 10 s.

### Phase 3: Query and answer service (3–4 weeks)
Detailed design, including the DSL roadmap: **[CLINICAL_QA_DESIGN.md](CLINICAL_QA_DESIGN.md)**.
- A FastAPI `QueryPlan` endpoint (authenticated, tenant-scoped), plan and answer caches scoped to patients in scope,
  and streaming narration with compacted inputs.
- More operators as reviewers need them (authorisation utilisation, administrative findings such as charges without
  attendance, provider-level views). Each comes with golden tests.
- Answer eval: post-check pass rate, a citation-validity sample, and a reviewer feedback loop.
- **Exit:** per-patient deterministic queries under 200 ms p95; narrated answers under 20 s p95; post-check pass ≥ 99%.

### Phase 4: Reviewer product and operations (4 weeks)
- Reviewer UI (timeline, evidence, conflicts, adjudication, exports); an audit trail of every view and decision.
- SLOs and alerting, load tests at 1M documents and 30K+ patients, disaster recovery (PITR), cost budgets per
  tenant, PHI-safe logging, a security review, and HIPAA/SOC 2 control evidence.
- **Exit:** production readiness review passed; first tenant onboarded.

### Phase 5: Continuous improvement (ongoing)
- Active learning: reviewer overrides and adjudications feed the gold set and the prompt and rule improvements.
- Distil or fine-tune a cheaper extractor for high-volume document types once the gold set is large enough.
- Expand coverage to new document types, payers' rules and requirement types.

---

## 7. Proposed SLOs (targets to agree with Backbone)

| SLO | Target |
|---|---|
| New document → queryable (real-time lane) | p95 < 5 min |
| Backfill / daily feed (batch lane) | < 24 h |
| Per-patient deterministic query | p95 < 200 ms |
| Collection-wide query at 1M documents | p95 < 10 s (warehouse-backed) |
| Narrated answer | p95 < 20 s |
| Extraction accuracy (gold set, critical fields: dates, intervals, disposition, presence) | ≥ 98% field-level |
| Answers passing post-check | ≥ 99% |
| Unverified-quote claim rate | < 0.5% (alert above) |

## 8. Risks and open questions

- **Clinical rule ownership.** Which evidence tiers, and which conflict policies, are acceptable to Backbone's
  clinical reviewers and to their clients' payers? These rules should be configurable per tenant or contract, with
  a version history.
- **Model change management.** Provider model updates can shift extraction. Pin model versions, keep the eval gate,
  and run shadow comparisons before switching.
- **Input quality.** OCR errors break quote verification; that needs fallback policies and rescans.
- **Patient matching errors** are the most damaging failure: wrong-patient evidence. Use conservative matching plus
  human review queues.
- **Cost variance** across tenants and document mixes. Enforce per-tenant budgets with alerts.
- **Regulatory scope:** BAA coverage for every vendor that touches PHI (LLM, OCR, observability).

## 9. Storage and retrieval choices: graph DB, RDF, RAG

**Graph database: not as the system of record; possibly later as a derived projection.**
- The domain *is* a graph (patient → episode → encounter → claims → documents, with corrects, copy-of and
  same-encounter edges), and we export it (`out/abstraction/*.graph.json`).
- But the product's queries are shallow (≤ 3 hops, always within one patient). The hard part is temporal joins,
  interval arithmetic, sums with bounds, and effective-dated plan rules. Postgres does all of that better.
- `WITH RECURSIVE` covers lineage chains such as a correction of a copy of a roster.
- A second store holding PHI doubles the consistency, security and compliance work.
- **When it pays off:**
  - patient identity resolution across sources (graph clustering);
  - provider and billing network analytics (e.g. charges without attendance across providers);
  - referral-pathway questions.
- Then run it as a CDC-fed projection; try the Apache AGE extension (openCypher inside Postgres) first.

**RDF / triple store: no. Use healthcare standards instead.**
- RDF's value is shared vocabularies and interoperability. In healthcare those come from FHIR and standard
  terminologies.
- SPARQL is awkward for interval and bounds arithmetic, and OWL reasoning doesn't fit procedural, temporal rules.
- **Instead:**
  - store SNOMED CT, LOINC and CPT codes next to our enums (PHQ-9 = LOINC 44261-6);
  - provide a FHIR export: `Encounter`, `Observation`, `CarePlan`/`Goal`, `DocumentReference`, and `Provenance`
    (which maps directly to claims plus evidence spans).
- An RDF serialization is a cheap derived export if a client ever requires linked data.

**RAG: never for computed answers; yes as a clearly labelled second tier.**
- Top-k retrieval cannot guarantee completeness: missing one no-show roster or correction changes the answer, as the
  ablation shows. It also cannot reconcile records or do arithmetic. Counts, minutes and compliance stay deterministic.
- **Where retrieval helps:**
  1. **Evidence-only answers** for questions outside the operators (e.g. blood pressure). Return cited passages,
     clearly labelled "retrieved, not computed", instead of a flat refusal.
  2. **Cross-patient semantic candidate search** (e.g. "notes mentioning housing instability"), then verify against
     the structured layer.
  3. **Words outside our fixed categories** in qualitative questions: search verified claims and observations, not
     raw chunks, so citations stay checkable.
  4. **Planner few-shot retrieval** of similar past question → plan pairs.
- **Implementation:** pgvector inside Postgres, filtered by tenant and patient. No separate vector DB. Confirm BAA
  coverage for the embedding model. Within one patient, structured filtering usually suffices without embeddings.

**What would change these choices:** the workload becoming dominated by variable-depth traversal (networks, identity,
referrals), or a contractual linked-data requirement.
