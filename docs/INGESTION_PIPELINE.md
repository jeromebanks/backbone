# Ingestion pipeline: production design

**Confidential:** part of a private submission (see `AGENTS.md`).
**Related:** [ROADMAP.md](ROADMAP.md) (whole-system plan, choke points) · human-facing version: [ingestion.html](ingestion.html).

## 1. Starting point and governing principle

**Today.** `python -m backbone ingest <paths>` does everything in one process:
- walks the folder and hashes every file;
- extracts new hashes in a thread pool;
- verifies quotes, writes claims;
- reconciles the patients it touched.

That is correct and idempotent, but it is a single-process batch job: it re-reads the whole input on every run and
handles one patient per document. It accepts only `.txt` files.

**Principle that makes scaling easy: reconciliation is order-independent.** Precedence follows document
relationships (corrections, copies, evidence tiers), never arrival or document date. So the pipeline needs **no
ordering guarantees**. A late correction, a resend that arrives after the correction, or the same file delivered
twice all reconcile to the same result. What the pipeline must guarantee instead is:

1. **Idempotent stages:** each stage is keyed by `(sha256, stage, version)`, so re-running it is a no-op.
2. **At-least-once delivery:** events may repeat; the idempotent stages absorb the repeats.
3. **Nothing is lost:** every document has a state row; failures end in a dead-letter state that is visible and
   retriable, never silent.

## 2. Target flow

```
sources: upload API · SFTP drop · EHR/FHIR feeds · fax gateway
   │
   ▼
[1 Intake] ── S3 put  s3://docs/{tenant}/{sha256}  (if-none-match → duplicates stop here)
   │          documents + document_jobs rows, outbox → document.received
   ▼
[2 Normalize] PDF text / OCR / HL7·FHIR·CCD → canonical text + coordinate map (page, line, bbox)
   │          split fax bundles into separate documents → document.normalized (one per part)
   ▼
[3 Classify & route]  doc type · patients mentioned · has clinical events? · near-duplicate? · priority
   │          ├─ no clinical content → state=skipped (kept for audit)
   │          ├─ near-duplicate → state=linked_copy (relation claim, no LLM)
   │          └─ → extract.requested {lane}
   ▼
[4 Extract]   interactive lane: real-time Claude API (patient under active review)
   │          bulk lane: Message Batches (backfills, nightly feeds; −50%)
   │          shared: prompt-cached fixed prefix, model routing by doc type, long-document chunking,
   │                  refusal/error retries → dead_letter after N attempts
   ▼
[5 Claims]    verify quotes → line/page spans · resolve patient per claim · write claims + job state in one tx
   │          outbox → patient.dirty {tenant, patient, episode}   (debounced per patient-episode)
   ▼
[6 Reconcile] one patient-episode per job, version-checked, idempotent (ms) → clinical tables, projections
   │          outbox → projection.updated
   ▼
[7 Publish]   invalidate answer caches scoped to the patient · CDC → analytics store · reviewer notifications
```

## 3. Stages in detail

| # | Stage | Consumes → produces | Idempotency key | Scales with | Failure handling |
|---|---|---|---|---|---|
| 1 | Intake | bytes + metadata → S3 object, `documents`, `document_jobs(received)`, `document.received` | `(tenant, sha256)`; conditional put | request rate (stateless) | rejected uploads return errors; a duplicate returns the existing ID and adds a source path |
| 2 | Normalize | `document.received` → canonical text, coordinate map, child documents for bundles | `(sha256, normalizer_version)` | CPU and OCR quota | unreadable or low OCR confidence → `needs_rescan` state, surfaced to ops |
| 3 | Classify & route | normalized text → doc type, mentioned patients, near-dup signature, lane | `(sha256, classifier_version)` | cheap model or heuristics; small | defaults to "extract" when unsure (never silently skips clinical content) |
| 4 | Extract | `extract.requested` → `Extraction` JSON (cached by `sha256.version.model`) | `(sha256, extractor_version, model)` = batch `custom_id` | **LLM token and batch quotas** (the real ceiling) | retry with backoff; refusal → fallback model; schema failure → retry → `dead_letter` |
| 5 | Claims | extraction → verified claims, per-claim `patient_ref` | `(sha256, extractor_version)`; replace claims for that document in one transaction | DB writes (~8 claims/doc measured) | unverified quotes are kept but flagged (R0). A quality gate halts the batch if the unverified rate exceeds its threshold |
| 6 | Reconcile | `patient.dirty` → clinical layer + projections | `(tenant, patient, episode, ruleset_version, claims_watermark)` | patients changed; ~4 ms each (measured) | pure function; a failed job is retried and the previous projection stays valid meanwhile |
| 7 | Publish | `projection.updated` → cache invalidation, CDC, notifications | `(patient, projection_version)` | trivial | retries; consumers are idempotent |

### Data model additions

```sql
-- object identity and lifecycle (one row per document; children for split bundles)
documents(tenant_id, sha256, parent_sha256, source, received_at, mime, pages, normalizer_version, ...)
document_jobs(tenant_id, sha256, state, stage_version, attempts, last_error, lane, priority,
              updated_at, PRIMARY KEY (tenant_id, sha256))
-- state ∈ received | normalized | classified | skipped | linked_copy | extract_queued | extracted
--         | claimed | reconciled | needs_rescan | dead_letter
outbox(id, topic, key, payload_ref, created_at, sent_at)        -- transactional outbox
dirty_patients(tenant_id, patient_id, episode_id, first_dirty_at, last_dirty_at)  -- coalescing set
claims(..., patient_ref, extractor_version, recorded_at, valid_from, valid_to)    -- per-claim patient, bitemporal
```

Events carry **references only** (tenant, sha256, patient ID), never document text or PHI.

## 4. The two extraction lanes

| | Interactive lane | Bulk lane |
|---|---|---|
| Use | documents for a patient under active review; a reviewer is waiting | backfills, nightly feeds, re-extraction after a version bump |
| API | real-time Messages API, structured outputs | Message Batches API (`custom_id = sha256:extractor_version:model`) |
| Latency target | p95 < 2 min from upload to claims | ≤ 24 h |
| Cost | list price (prompt caching on the fixed prefix) | −50% batch discount, plus caching |
| Concurrency control | shared token bucket (Redis) sized to the tokens-per-minute limit, per tenant | batch size and count limits; submission throttled by a Temporal workflow |
| Promotion | a reviewer opening a patient promotes that patient's queued documents from bulk to interactive | n/a |

Both lanes share:
- one extraction contract (`schema.py`) and prompt;
- the content-addressed cache;
- model routing, decided by the gold-set eval (e.g. Opus for notes, cheaper models for rosters and schedule exports
  where parity is shown);
- **long-document chunking**: split by section or page, extract each chunk, stitch events by encounter ID, and treat
  cross-chunk relations as `references`.

## 5. Coalescing and reconciliation

- `patient.dirty` is an upsert into `dirty_patients`. A scheduler drains entries older than the debounce window
  (e.g. 30 s interactive, 5 min bulk), so 20 documents for one patient in a batch become **one** reconcile.
- Reconcile jobs record the claims watermark they read. If newer claims arrive mid-job, the patient is re-marked
  dirty, so there are no lost updates and no locks.
- Ruleset version bumps enqueue every affected patient in the background. This is cheap (no LLM).

## 6. Backfills and reprocessing

- **Backfill:** a Temporal workflow reads an S3 Inventory manifest (never `LIST`), pages through it, and submits to
  the bulk lane with checkpoints. It can be paused and resumed, and it is throttled per tenant.
- **Extractor or model change:**
  1. A shadow run on a stratified sample is scored against the gold set and diffed at the level of reconciled
     outcomes.
  2. The change is promoted only if field-level accuracy holds.
  3. Only the affected document types are then re-extracted, in the bulk lane. The old extractions are kept for
     reproducibility.
- **Normalizer change:** re-normalize and re-classify. Re-extract only if the canonical text hash changed.

## 7. Operating it

- **Fairness:** a weighted queue per tenant and lane. The interactive lane has reserved capacity, so a backfill never
  starves reviewers.
- **Autoscaling:** workers scale on queue depth (KEDA). The binding constraint is LLM quota, so the scaling target is
  "keep the token bucket full", not CPU.
- **Quality gates:** each batch is halted when any of these drifts above its threshold:
  - schema-failure rate;
  - unverified-quote rate;
  - `U-` (unidentified contact) rate;
  - near-duplicate rate.
- **Observability:**
  - per-stage latency;
  - queue depth;
  - tokens and $ per document, by model, lane and tenant;
  - attempts and dead-letter counts;
  - document lineage via `document_jobs`.
  These are OpenTelemetry traces keyed by sha256, with no PHI in spans.
- **Security:** S3 SSE-KMS and object lock; least-privilege IAM per stage; PHI only in S3 and Postgres; audit
  events for every read.

## 8. Capacity and cost (estimates from measured per-document figures)

*Measured:* 8,318 input tokens and 1,574 output tokens per document; 13.2 s mean latency; $0.045/doc at the list
price reported by the CLI; 0.53 docs/s at concurrency 8.

- **Steady state:** 5K docs/day ≈ 3.5 docs/min on average. That is comfortable even entirely on the interactive lane.
- **Backfill:** 1M docs ≈ 10B tokens. The duration is set by token and batch quotas, not by worker count.
- **Cost levers, in order:**
  1. the batch discount (−50%);
  2. model routing (Sonnet ≈ ½ price, Haiku ≈ 1/40 where accuracy holds);
  3. skipping non-clinical documents and near-duplicates;
  4. prompt caching of the ~90% fixed prefix.

  Together these are the difference between **~$45K and ~$15K with Opus, or ~$8K with Sonnet** for a 1M-document
  backfill, assuming 15% of documents are skipped.
  `ingestion.html` has an interactive estimator.

## 9. Testing strategy

- Run the full pipeline locally with LocalStack (S3/SQS), Postgres and the Temporal dev server. The LLM is replayed
  from `cache/extractions/`, so tests make no LLM calls.
- Property tests:
  - **duplicate delivery:** every event delivered 2–3×, so the results are byte-identical;
  - **shuffled order:** documents in random order, giving identical projections. This is the order-independence
    guarantee, and the existing golden values must still hold;
  - **crash injection:** kill a worker between stages; on resume, nothing is lost or duplicated.
- Load tests: synthetic 1M-document manifests through the bulk lane with a stubbed LLM to measure the plumbing, plus a
  small real-LLM sample to calibrate quotas.

## 10. Rollout

| Step | Build | Exit criteria |
|---|---|---|
| 1 | `document_jobs` state machine inside the current codebase; hash once at intake; no rescans | the existing test suite passes; re-ingest touches 0 files; crash/duplicate property tests pass |
| 2 | S3 + outbox events + Temporal; interactive and bulk lanes; token bucket | 50K-doc backfill within budget; interactive p95 < 2 min |
| 3 | Normalization (PDF/OCR/HL7), bundle splitting, classification, near-duplicate linking | gold set covers PDF and fax; skip and link rates measured; no clinical document wrongly skipped in the audit sample |
| 4 | Fairness, autoscaling, quality gates, dashboards, 1M load test | SLOs met under load; drift gates trip in fault-injection tests |
