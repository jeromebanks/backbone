# Backbone AI Take-Home: Clinical Intelligence Prototype

## Your Role

You are Claude Code Opus, acting as a senior software engineer and systems architect.

We are implementing a take-home engineering challenge for Backbone AI. The objective is to demonstrate strong engineering judgment, sound data modeling, deterministic computation, evidence provenance, and an architecture that can scale to large clinical document collections.

**Implement a working end-to-end prototype, not merely an architecture document.**

The exercise has a suggested time budget of 2–5 hours. Prioritize correctness, auditability, simplicity, and meaningful benchmarks over unnecessary infrastructure or polish.

Read the supplied `Problem Statement.pdf`, `questions.json`, and all documents in `documents/` before finalizing the design. Treat the problem statement as authoritative.

Do not hardcode answers, patient-specific facts, encounter corrections, or special cases based on the development questions.

---

# 1. Central Architectural Idea

We want to build a system that transforms unstructured clinical documentation into a persistent, structured clinical abstraction, then answers natural-language questions through deterministic computations over that abstraction.

The architecture has two complementary pipelines.

### Knowledge construction

```text
Clinical documents
       |
       v
Document parsing and classification
       |
       v
LLM-assisted structured evidence extraction
       |
       v
Typed clinical claims with provenance
       |
       v
Entity resolution and evidence reconciliation
       |
       v
Persistent temporal clinical evidence graph
       |
       v
Reconciled clinical facts and projections
```

### Question answering

```text
Natural-language question
       |
       v
LLM semantic interpretation
       |
       v
Typed Python query DSL / intermediate representation
       |
       v
Validation and SQL compilation
       |
       v
Deterministic SQL execution
       |
       v
Results + calculations + evidence references
       |
       v
Auditable natural-language answer
```

**The LLM operates primarily at semantic boundaries. The core of the system is conventional, deterministic software.**

The LLM interprets clinical language and user questions. It should not be responsible for arithmetic, session counting, final entity reconciliation, or deciding compliance by intuition.

A qualitative clinical summary may use LLM-assisted synthesis, but only over retrieved, structured, evidence-backed observations.

---

# 2. Knowledge Graph Representation

We discussed several possible representations:

- RDF triples and SPARQL
- RDF-star with provenance attached to assertions
- Property graphs and graph databases
- Traditional relational schemas
- Hierarchical text formats similar to OKF
- JSON-based document models

Our architectural decision is:

**Use a logical temporal evidence graph, physically persisted in SQLite using relational tables and JSON where appropriate.**

We want graph semantics without introducing unnecessary graph-database infrastructure.

SQLite is sufficient for the prototype and supports deterministic queries, indexes, joins, constraints, transactions, and persistent storage.

Do not introduce Neo4j, a triple store, a vector database, or another service without a concrete requirement.

### RDF inspiration

RDF's subject–predicate–object model is conceptually useful, especially for attaching evidence to assertions.

However, a pure RDF representation is not necessary for this bounded domain. Temporal joins, numerical aggregations, and reconciliation rules still require explicit semantics regardless of the storage model.

Preserve RDF-like flexibility through:

- Stable entity identifiers
- Typed relationships
- First-class claims
- Explicit provenance
- Extensible predicates
- Well-defined domain semantics

It should be possible to export the graph into an RDF-compatible representation later, but implementing RDF export is not a prototype requirement.

### OKF inspiration

Hierarchical text formats may be useful for human inspection, agent context, Git diffs, and portability.

However, hierarchical text files should not be the operational database.

Provide JSON exports of the clinical abstraction, preferably organized by patient and episode. These should be derived from the database, not independently maintained sources of truth.

---

# 3. Critical Modeling Principle: Claims Are Not Facts

This is the most important distinction in the entire architecture.

Clinical documents contain assertions about care. Different documents may describe the same event, provide complementary information, contradict one another, or correct earlier records.

We must distinguish:

1. What a source document asserts.
2. What evidence supports that assertion.
3. What the system concludes after reconciliation.
4. What remains uncertain or disputed.

For example:

```text
Claim C1:
  subject: Encounter E112
  predicate: therapy_minutes
  value: 45
  source: Clinical note
  status: supported

Claim C2:
  subject: Encounter E112
  predicate: therapy_minutes
  value: 55
  source: Attendance record
  status: disputed
```

These claims must coexist.

The system may determine that 45 minutes is the appropriate reconciled value, but it must retain the conflicting assertion and explain the resolution.

Do not use last-write-wins.

A later record does not automatically supersede an earlier one.

Distinguish explicit corrections from independent observations, duplicated records, and genuinely conflicting evidence.

### Epistemic state

The system should represent what is:

- Established by the available evidence
- Disputed by conflicting evidence
- Unknown because evidence is missing
- Unresolvable without additional documentation

Where appropriate, distinguish a zero value from a missing value.

Do not interpret absence of documentation as proof that care did not occur unless the available records justify that conclusion.

For compliance questions, support at least:

```text
MET
NOT_MET
UNDETERMINED
```

The reconciliation and compliance logic should document the conditions under which each result is justified.

---

# 4. Event-Centered Domain Model

This is an event-centered graph rather than a completely generic graph of arbitrary assertions.

The natural unit of clinical activity is a care encounter.

An encounter may have several records, multiple contact segments, observations, and relationships to treatment requirements.

Suggested first-class entities:

### Patient

Stable patient identifier and relevant demographics.

### Episode

A period or course of care associated with a patient.

### Encounter

A distinct clinical service event.

Attributes may include:

- Stable encounter identity
- Patient
- Episode
- Service date
- Service type
- Provider
- Appointment identifier
- Eligibility / resolution status

### ContactSegment

An interval of actual therapeutic contact.

Attributes may include:

- Parent encounter
- Start and end
- Actual patient-contact duration
- Contact modality
- Evidence
- Uncertainty

A single encounter may contain multiple contact segments.

### TreatmentPlan

A treatment plan with temporal validity.

Attributes:

- Patient and episode
- Effective start/end
- Goals and requirements
- Revisions
- Supporting evidence

### Requirement

A measurable care obligation, such as required therapy days, sessions, or minutes per week.

Do not conflate days, sessions, and minutes.

### Observation

Clinical findings, symptom descriptions, assessments, or progress observations.

Include temporal context and evidence.

Distinguish separate assessments from copied or repeated descriptions of the same assessment.

### Document

An immutable source record.

Include content hash, identity, document metadata, source content, and ingestion information.

### Evidence

A precise reference to a source passage.

Include document identity and line references or character offsets where feasible.

Preserve enough information for a reviewer to locate and verify a claim.

### Claim

A source-backed assertion about an entity, event, relationship, quantity, or observation.

Claims may have structured values, explicit provenance, and reconciliation status.

### Relationships

The graph should support relationships such as:

```text
Patient -> hasEpisode -> Episode
Episode -> containsEncounter -> Encounter
Encounter -> hasContactSegment -> ContactSegment
Encounter -> documentedBy -> Document
Encounter -> hasObservation -> Observation
TreatmentPlan -> hasRequirement -> Requirement
Claim -> supportedBy -> Evidence
Evidence -> locatedIn -> Document
Claim -> contradicts -> Claim
Claim -> supersedes -> Claim
```

Not every relationship requires a generic edges table. Use explicit foreign keys for stable domain relationships and an extensible graph representation where it adds value.

Avoid implementing redundant representations that can drift apart.

---

# 5. Relational Persistence

Use SQLite as the canonical persistent store.

A reasonable starting schema includes:

```text
documents
entities
claims
evidence
encounters
contact_segments
treatment_plans
requirements
observations
```

This is a suggested logical model, not a mandatory exact schema.

Prefer explicit relational fields for frequently filtered or aggregated attributes. Use JSON for variable structured properties.

Enforce referential integrity and useful uniqueness constraints.

### Separate evidence from projections

Maintain two distinct levels of clinical information:

**Evidence layer**

Source documents, extracted claims, supporting passages, conflicts, extraction metadata.

**Reconciled clinical layer**

Resolved encounters, contact intervals, plan requirements, assessments, and explicit unresolved states.

The reconciled layer should be derived from the evidence layer rather than independently authored.

Keep reconciliation rules versioned or otherwise identifiable so results can be reproduced and affected projections can be rebuilt if rules change.

### Persistence and idempotency

A restarted process must reuse the saved clinical abstraction.

Identical duplicate documents must not change clinical results.

Use content hashes for document deduplication, while distinguishing byte-identical duplicate files from semantically overlapping clinical documentation.

New questions should reuse existing abstractions rather than trigger complete extraction again.

---

# 6. Encounter Identity and Reconciliation

Be especially careful about encounter identity.

A scheduled appointment, an attendance record, a clinical note, and a telehealth platform record may describe one encounter from different perspectives.

They must not automatically become separate sessions.

Likewise, multiple calls or contact segments do not necessarily mean multiple encounters.

### Important example: January 21 telehealth

The provided telehealth record describes:

- Encounter `HG-E112`
- Appointment `HG-A112`
- First connection: 13:00–13:20
- Disconnection: 13:20–13:30
- Second connection: 13:30–13:55
- Both calls belong to the same appointment and clinical encounter

The correct interpretation of that specific document is:

```text
Clinical encounters: 1
Connection segments: 2
Actual therapy contact: 45 minutes
Non-contact interruption: 10 minutes
```

This example demonstrates the distinction between connection events, clinical encounters, and therapeutic contact duration.

Implement general rules that can recognize such situations rather than hardcoding the particular encounter.

### Reconciliation considerations

Use stable clinical identifiers when available.

When identifiers are missing, candidate matching may consider:

- Patient
- Service date
- Service type
- Appointment identifier
- Encounter identifier
- Provider
- Time interval
- Source relationships

Avoid merging two truly distinct services simply because they occur on the same day.

Preserve uncertainty when there is insufficient evidence to establish identity.

Document inclusion and exclusion decisions when they affect calculated answers.

---

# 7. Temporal Semantics

Time is a first-class part of the clinical representation.

At minimum, distinguish:

- Service/event time
- Treatment-plan effective time
- Document creation/signing time
- Correction or amendment time
- Ingestion time

These timestamps serve different purposes.

The treatment requirements applicable to an encounter depend on the plan in effect at the relevant clinical time, not necessarily the latest plan in the database.

Support effective-date joins between care events and treatment plans.

Weekly calculations should use Monday–Sunday periods, as specified by the questions.

Consider treatment-plan changes occurring within a reporting week. Do not silently apply the newest plan to the whole week without a justified rule.

Represent any unresolved interpretation explicitly.

---

# 8. Python Clinical Query DSL

The question-answering system should use a composable, typed Python DSL that compiles to SQL.

**Do not have the LLM generate arbitrary SQL directly.**

The DSL expresses clinical query semantics independently of the physical database schema.

Conceptually:

```python
query = (
    care.for_patient("Rowan Mercer")
    .during("2026-01-05", "2026-01-30")
    .therapy()
    .eligible()
    .weekly()
    .metrics(
        TherapyMinutes(),
        SessionCount(),
        TherapyDays(),
    )
    .with_evidence()
)

result = query.execute(db)
```

For treatment-plan compliance:

```python
query = (
    care.for_patient("Rowan Mercer")
    .during("2026-01-05", "2026-01-30")
    .therapy()
    .weekly()
    .evaluate(TreatmentPlanRequirements())
    .with_evidence()
)
```

These are illustrative APIs. Choose a practical implementation that fits the time budget.

### DSL semantics

Prefer domain operators such as:

```text
TherapyMinutes()
SessionCount()
TherapyDays()
TreatmentPlanRequirements()
```

rather than requiring the LLM to know raw SQL columns.

For example, `TherapyMinutes()` should implement the rules for actual therapeutic contact time, including eligible encounters and disconnected intervals.

`SessionCount()` should operate on reconciled clinical encounters rather than individual records or connection segments.

### Query AST

The Python DSL should construct a typed query representation or AST.

The AST can then be:

- Validated
- Logged
- Compiled to parameterized SQL
- Executed
- Explained
- Tested

Provide the equivalent of:

```python
query.to_sql()
query.explain()
query.execute(db)
```

Avoid embedding patient-specific values into generated SQL text. Use bound parameters.

### Safety and reproducibility

Do not execute arbitrary LLM-generated Python.

Instead:

1. Ask the LLM to emit a structured query specification.
2. Validate it against a strict schema.
3. Reconstruct permitted Python DSL objects.
4. Compile those objects into SQL.
5. Execute the resulting read-only query.

A query that cannot be represented by supported operators should fail explicitly instead of producing an improvised answer.

---

# 9. Natural Language to DSL Translation

The supplied `questions.json` contains the development questions.

Implement a semantic translation layer that converts questions into structured query specifications using the supported DSL.

For example:

```json
{
  "operation": "aggregate_encounters",
  "patient": "Rowan Mercer",
  "period": {
    "start": "2026-01-05",
    "end": "2026-01-30"
  },
  "metrics": [
    "therapy_minutes",
    "therapy_hours"
  ],
  "group_by": ["week"],
  "include_evidence": true
}
```

The query compiler then generates deterministic SQL.

The point is not to hardcode the five development questions. Define reusable operators that support related unseen questions.

Suggested operations include:

```text
aggregate_encounters
evaluate_requirements
reconstruct_timeline
compare_periods
summarize_observations
```

These operations should reuse a common composable query framework rather than becoming five unrelated functions.

### Multiple query operations

Some natural-language questions require several queries.

Allow a query plan to contain multiple subqueries and combine their results deterministically.

The model may determine which operations are needed, but the actual computations must be performed in code.

### Qualitative questions

Symptom progression and clinical narratives may require more than SQL aggregation.

Use structured observations, assessments, chronology, and source evidence as the grounding for synthesis.

If an LLM produces the final narrative, distinguish interpretation from documented facts, and require evidence references.

Do not claim progress or improvement without supporting clinical observations.

---

# 10. Deterministic Querying and Scalability

Our core architectural hypothesis is that a persistent clinical abstraction makes most repeated questions inexpensive.

Once documents have been interpreted and reconciled, the supplied questions become conventional analytical queries:

- `COUNT(DISTINCT encounter_id)`
- `SUM(actual_contact_minutes)`
- `COUNT(DISTINCT service_date)`
- Grouping by week
- Temporal joins against treatment plans
- Comparisons across periods
- Indexed evidence joins

The query layer should not need to reread or reprocess the original clinical corpus for every new question.

### Indexing

Consider indexes for:

- Patient identity
- Encounter dates
- Encounter identifiers
- Service type
- Treatment-plan effective periods
- Claim subjects
- Evidence document references

### Materialized summaries

If useful, demonstrate how patient-week aggregations could be persisted:

```text
patient_weekly_therapy
----------------------
patient_id
week_start
service_type
session_count
therapy_days
total_minutes
compliance_status
```

These must be deterministic, rebuildable projections, not additional clinical sources of truth.

Do not add a complicated materialization framework unless it materially improves the prototype.

### Scaling expectations

The problem statement describes 500,000+ clinical documents and asks about bottlenecks at approximately one million documents.

We expect LLM extraction throughput, token cost, and reconciliation fan-out to be important scaling concerns.

Indexed relational querying should remain efficient for typical patient-specific questions.

However, do not assume that all analytical questions are constant-time or independent of corpus size.

Collection-wide joins, large evidence traversals, and complex reconciliation can become expensive.

Measure actual performance and distinguish measured results from estimates.

**For this implementation, prioritize query correctness and deterministic reuse. Discuss large-scale ingestion architecture separately rather than prematurely implementing distributed infrastructure.**

---

# 11. Exact Development Questions

Read the supplied `questions.json` and preserve the exact wording and IDs.

The questions cover:

**DEV-01:** Therapy session counts by service type, total sessions, distinct attendance days, and exclusion/duplication decisions.

**DEV-02:** Actual therapy minutes and hours, overall and by Monday–Sunday week, including unresolved conclusions.

**DEV-03:** Whether delivered care met the treatment requirements applicable to each week.

**DEV-04:** Reconstruction of January 19 and January 21, reconciling attendance records, clinical notes, later documentation, and telehealth records.

**DEV-05:** Documented symptom course, reason for additional individual contact on January 19, distinct symptom assessments, and supported versus unsupported progress conclusions.

These are development tests of the architecture, not five special cases to encode.

The problem statement also describes collection-wide questions, consecutive below-requirement weeks, and before/after treatment-plan changes. Design reusable operators for these even if the supplied development dataset is narrower.

---

# 12. Auditability

Every numerical answer should provide enough information for a reviewer to independently reconstruct the calculation.

For example:

```json
{
  "patient": "HG-M042",
  "date": "2026-01-21",
  "encounter_id": "HG-E112",
  "sessions": 1,
  "therapy_minutes": 45,
  "calculation": "20 + 25",
  "evidence": [
    {
      "document": "BH-D106",
      "location": "lines 5-7"
    },
    {
      "document": "BH-D106",
      "location": "lines 15-19"
    }
  ]
}
```

Preserve the supporting records and decisions that resulted in a session being included or excluded.

A reviewer should be able to trace a collection-wide result to:

```text
Collection-wide finding
    -> Patient results
    -> Encounter contributions
    -> Reconciled claims
    -> Evidence passages
    -> Original documents
```

The supporting evidence must be real and verifiable. Never manufacture source references.

---

# 13. Testing Strategy

Implement meaningful tests, not just happy-path demonstrations.

At minimum, test:

1. **Idempotency:** Ingesting an identical document twice does not change clinical totals.
2. **Restart persistence:** A new process can answer questions using the saved abstraction without repeating extraction.
3. **Encounter deduplication:** Multiple records describing one encounter do not create duplicate sessions.
4. **Contact segmentation:** Two connections belonging to one encounter count as one encounter with the correct contact duration.
5. **Conflicting claims:** Contradictory source records remain inspectable.
6. **Temporal plans:** Requirements are resolved using effective dates.
7. **Missing documentation:** An unknown value does not silently become zero.
8. **Question paraphrases:** Equivalent questions should produce equivalent query plans and results.
9. **SQL determinism:** Repeated execution against unchanged data produces identical calculated results.
10. **Provenance:** Every consequential result is traceable to actual source passages.

Use the January 21 example as an important regression test, but avoid hardcoding it in general production logic.

---

# 14. Benchmarking and Observability

Record:

- Number of documents processed
- Initial extraction and processing time
- Model name and settings
- Model calls and token usage where available
- Approximate model cost
- SQLite database size
- Patient-level query latency
- Collection-wide query latency
- Repeated query latency
- Restart behavior
- Number of extracted claims and resolved encounters

Measure wall-clock timing rather than reporting assumed performance.

Distinguish measured values from projections for 500K or 1M documents.

Identify the expected first bottleneck at one million documents and point to the code or operation responsible.

Also record an observed limitation and a concrete investigation or experiment that could address it.

---

# 15. Implementation Priorities

The recommended sequence is:

### Phase 1 — Inspect and design

Read the problem statement, supplied questions, and all clinical documents.

Identify the entity types, document relationships, conflicting evidence, and temporal requirements.

Define the minimal schema and typed extraction contracts.

### Phase 2 — Evidence extraction and persistence

Implement document ingestion, structured extraction, source spans, content hashing, and persistent storage.

Save extracted claims independently from reconciled facts.

### Phase 3 — Reconciliation

Implement encounter identity resolution, contact segment aggregation, eligibility decisions, temporal treatment-plan relationships, and conflict representation.

Use deterministic rules wherever possible.

### Phase 4 — Python query DSL

Implement the domain operators, typed query representation, SQL compiler, and executor.

Keep the DSL small but composable.

### Phase 5 — Natural-language query translation

Use an LLM to translate questions into validated DSL representations.

Provide deterministic answers and provenance.

### Phase 6 — Validation

Run all five development questions.

Inspect results against original records.

Test duplicate ingestion, process restart, and related unseen questions.

### Phase 7 — Benchmarks and documentation

Generate outputs, execution logs, benchmark results, and a concise README.

Document architectural decisions, alternatives, limitations, and scaling expectations.

---

# 16. Deliverables

Produce a runnable repository containing:

- Source code
- Dependency/setup instructions
- CLI for processing documents
- CLI for answering new questions
- Persistent SQLite clinical abstraction
- Patient-oriented JSON abstraction export
- Answers to all five development questions
- Supporting evidence and calculation details
- Tests
- Execution logs
- Benchmark results
- README with architecture and tradeoffs

A CLI is sufficient; do not build a web UI.

The system should support workflows similar to:

```bash
python -m backbone ingest documents/
python -m backbone answer questions.json
python -m backbone export --patient HG-M042
python -m backbone benchmark
```

These are illustrative commands, not mandatory interface names.

The README should clearly explain how to add documents and answer new questions without rebuilding the existing abstraction.

Disclose AI assistance and model choices as requested by the problem statement.

---

# 17. Engineering Judgment and Constraints

Avoid unnecessary complexity.

Do not implement distributed workers, Kubernetes, orchestration frameworks, vector indexes, elaborate ontologies, or full RDF infrastructure simply to demonstrate architectural ambition.

Use a modest number of clear abstractions.

Prefer explicit domain semantics over a generic graph engine that knows nothing about clinical care.

Do not let the LLM make arbitrary numerical decisions.

Do not collapse conflicting evidence into a single untraceable fact.

Do not claim certainty when documentation is incomplete.

Do not hardcode development answers.

Do not assume the most recent document is authoritative.

Do not optimize query performance at the expense of clinical correctness.

Do not spend excessive time building infrastructure unrelated to the exercise.

A smaller, fully functioning, inspectable implementation is better than an ambitious but incomplete one.

---

# 18. What Makes This Architecture Distinctive

The intended contribution is not simply extracting information from clinical notes or applying RAG.

It is the combination of:

**A temporal evidence graph**

Represents what happened, what documents assert happened, and what remains uncertain.

**A persistent semantic abstraction**

Allows repeated questions without repeated document interpretation.

**A typed Python clinical query DSL**

Separates natural-language understanding from deterministic query semantics.

**A SQL compiler**

Turns clinical questions into reproducible computations over reconciled clinical records.

**An audit trail**

Connects every computed finding to individual services, reconciliation decisions, and original source passages.

This architecture creates a reusable clinical intelligence system rather than a question-answering script.

---

# 19. Begin Implementation

Start by inspecting the repository, all supplied materials, and the existing development environment.

Summarize the proposed schema, extraction contract, reconciliation approach, and query DSL in a concise implementation plan.

Then proceed with implementation.

Make sensible technical choices without repeatedly asking for confirmation.

If a design decision is ambiguous, choose the simplest approach consistent with correctness, provenance, and extensibility. Document the tradeoff.

Keep scope aligned with the 2–5-hour exercise.

**The primary success criterion is not merely producing five answers. It is demonstrating a reusable, deterministic, evidence-backed system whose conclusions can be independently audited and whose abstractions survive process restarts and new questions.**
