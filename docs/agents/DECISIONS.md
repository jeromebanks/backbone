# Design decisions (lightweight ADR log)

Each entry: decision · why · rejected alternatives · status. Add new entries at the bottom.

1. **SQLite relational store with graph semantics; no graph DB, triple store or vector DB.**
   - **Why:** the domain is bounded; the queries are temporal joins and aggregations; it is reproducible from one
     file. The graph view is exported (`.graph.json`), not stored.
   - **Rejected:** Neo4j, RDF/SPARQL, embeddings and RAG.
   - **Status:** accepted.
2. **Event-centred model: the encounter is the hub.** Documents, claims and intervals hang off encounters.
   Generic `entities`/`edges` tables were rejected, since they would drift from the typed tables.
3. **Claims vs facts.**
   - **Decision:** the evidence layer (`claims`) is separate from the derived clinical layer, which is rebuilt per
     patient.
   - **Why:** reviewers trace every number to source passages; rules can change without re-extraction.
4. **The LLM extracts intervals, never minutes.**
   - **Why:** stated durations are traps here. D113 states 45 min, but Rowan was present 30. Group notes give
     scheduled times while the patient arrived late or left early.
   - **Rejected:** extracting `therapy_minutes` claims (INIT.md's example).
5. **Precedence by relationship, never by date.**
   - **Decision:** explicit field-scoped corrections; retransmissions and copies carry no weight; evidence tiers.
   - **Why:** D104 (received Jan 26) re-sends the uncorrected roster. Last-write-wins would undo D103's correction.
   - **Measured:** the ablation shows the minutes change and an impossible overlap appears.
6. **Uncertainty as bounds, with three-valued verdicts.**
   - **Why:** E115 has two signed notes, 40 vs 50 min. Picking either flips week 4 to a confident MET or NOT_MET
     (measured in the ablation).
   - **Rejected:** choosing by note role, signature time or majority.
7. **Quotes verified by code; line numbers computed by code.**
   - **Why:** evidence must be real.
   - **Rejected:** trusting LLM-reported locations.
8. **Query layer: "operators now, DSL later".** Agreed with the user.
   - **Decision:** a validated JSON `QueryPlan` over four domain operators is the DSL. A fluent Python builder
     emits the same plan.
   - **Rejected:** INIT.md's generic NL → DSL → AST → SQL compiler. It was too costly for the time budget and could
     not express the explanation halves of the questions.
   - **Principles kept:** shared semantics in `project.py`; composable typed plans; structured results.
9. **The LLM backend is the user's Claude subscription** via `claude -p --json-schema`; `anthropic-api` is an
   alternative.
   - **Why:** the user's choice; there is no API key.
   - **Consequence:** the cost figures are list-price equivalents.
10. **Treatment-plan revisions.**
    - **Decision:** the latest effective_start per metric supersedes. A week that spans a revision is judged on
      whole-week totals against each set; disagreement gives UNDETERMINED. Identical restatements count once.
      Same-start differences are a conflict.
    - **Rejected:** comparing partial-week segments against weekly goals (an early bug that produced false
      NOT_MET), and ANDing overlapping plans.
11. **Collection-scale output caps** (`DETAIL_LIMIT = 200`).
    - **Why:** the first version of the operators built per-row detail and O(groups × n) groupings, which took
      minutes at 10K synthetic patients.
    - **Decision:** totals are always complete; detail is capped with a note.
12. **Expected answers live only in tests.** They were derived by hand before coding and protect against
    overfitting the production code to `questions.json`.

13. **No graph DB or RDF store as the system of record.**
    - **Why:** queries are shallow, temporal and aggregation-heavy; Postgres plus `WITH RECURSIVE` covers lineage.
    - **Graph DB later:** only as a CDC-fed projection, for identity resolution or provider-network analytics.
    - **RDF:** replaced by standard codes plus a FHIR export (`Provenance` ↔ claims).
    - Details: `docs/ROADMAP.md` §9.
14. **No RAG for computed answers.** Retrieval cannot guarantee completeness, reconcile records, or do arithmetic.
    It is allowed as a labelled "retrieved, not computed" tier, for cross-patient candidate search, and for planner
    few-shots, using pgvector in Postgres over verified claims.
15. **Ingestion is event-driven with idempotent stages and no ordering guarantees.**
    - **Why:** order-independent reconciliation makes that safe.
    - **Design:** two extraction lanes (interactive and Message Batches); reconciliation coalesced per patient-episode.
    - Spec: `docs/INGESTION_PIPELINE.md`.

16. **Clinician Q&A keeps the QueryPlan DSL as the only bridge from language to computation.**
    - Production adds a template fast path for common intents, compact digests for narration, streaming, a
      verification gate (regenerate, then template fallback) and three labelled answer tiers
      (computed / retrieved / unsupported).
    - Follow-ups edit the previous plan.
    - The Claude Code `clinical-qa` skill is the single-user form of the same contract.
    - Design: `docs/CLINICAL_QA_DESIGN.md`.
17. **A post-check line citation must be backed by an evidence passage in the results.** A document with no
    passages cannot back any line reference. (Earlier, unbacked citations to such documents passed unchecked.)
    A range `L6–9` is backed only if every line 6..9 is inside some passage; checking only the endpoints let
    `L1–10` pass on passages L1 and L10 (#16).
18. **Field corrections are a graph, not a sequence.**
    - **Decision:** corrections are resolved by following old → new edges to their end, whatever order the claims
      arrive in. Competing corrections of one value, or a cycle, keep every alternative as bounds plus a conflict.
      A correction that cannot be applied is reported.
    - **Rejected:** applying them in claim/hash order (first-match-wins made the result depend on sha256 order,
      #9), and choosing between competing corrections by document date (decision 5).
19. **Copy relations are scoped to the records they name** (an encounter or form ID, else a date). Only a relation
    that names neither covers its whole document. A document can resend one record and add a new one (#22).
20. **A correction that changed a number is part of the encounter's provenance.** Its relation claim joins the
    encounter's `claim_ids` unless another claim of the same document there already cites the same lines. That keeps
    the corpus's D103 evidence unchanged while making a relation-only correction citable (#23).
    - **Rejected:** a separate decision-claims query in each operator. It adds SQL to every envelope, which would
      change all saved results, and it would have to be repeated in each operator.

## Open questions / likely next decisions

- Persist a `patient_week` projection and compute collection-wide compliance as set-based SQL (6.2 s at 10K
  patients today).
- An extraction agreement harness (k runs, cheaper models) to pick the extractor model and find unstable fields.
- Treat passing mentions as `reference`s rather than service events, to reduce `U-` contacts.
- A second planning round, and narrator input capping.
