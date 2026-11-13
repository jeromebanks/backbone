# Architecture

## Layers

| Layer | Produced by | Tables | Mutability |
|---|---|---|---|
| Source | the filesystem | `documents` (sha256 PK, `doc_label`, `paths` JSON, `text`, `patient_mrn`) | append; a duplicate file adds a path |
| Extraction | `extract.py` (LLM) | `extractions` (raw JSON, latency, tokens, cost) + `cache/extractions/*.json` | keyed by (sha256, `EXTRACTOR_VERSION`, model) |
| Evidence | `ingest.build_claims` | `claims` (one row per assertion; `payload` JSON; `evidence` = verified spans; `verified`) | rebuilt per document on re-extraction |
| Clinical | `reconcile.py` | `patients`, `encounters`, `encounter_intervals`, `plan_requirements`, `assessments`, `observations`, `decisions`, `conflicts` | **derived**; deleted and rebuilt per patient |
| Projection | `project.py` + view `v_encounter_week` | none persisted (computed per query) | pure |
| Answers | `answer.py` | `answer_cache`, `out/answers/*.json|md` | keyed by question + fingerprint |
| Ops | `cli.py` | `run_log` | append |

## Module map

```
schema.py      Pydantic extraction contract (DocumentInfo, ServiceEvent, Relation, Assessment, Observation, PlanRequirement)
extract.py     SYSTEM prompt, extract_document() with file cache
llm.py         complete_json(): claude-cli | anthropic-api backends, schema sanitising, retries, usage capture
evidence.py    DocumentIndex.locate(quote) → line span (exact | normalized | fuzzy ≥0.92 | missing)
ingest.py      discover → sha256 → documents → parallel extract → build_claims → affected patient MRNs
intervals.py   minute-resolution interval algebra: normalize, subtract, intersect, total, overlaps
reconcile.py   reconcile_patient(mrn, claims) → Result (pure) ; persist() ; reconcile_patients()
project.py     select_encounters, aggregate (bounds), requirement_sets_on, weekly_compliance, plan_change_dates,
               evaluate_requirement, consecutive_runs  ← the ONLY place clinical numbers are computed
query.py       Scope, CareStep/ComplianceStep/TimelineStep/CompareStep, QueryPlan, execute_plan()
operators.py   care, compliance, timeline, compare → envelope; evidence/decision/conflict lookups
dsl.py         fluent builder → QueryPlan
answer.py      directory(), planner → execute → narrator → postcheck(); answer cache; verify_answers()
export.py      out/abstraction/<MRN>.json (nested) and .graph.json (nodes/edges)
bench.py       measured benchmarks; ablation.py naive-rule experiment
cli.py         argparse entry point (python -m backbone …)
```

## Key identifiers

- **Document identity** is `sha256`. `doc_label` is the header `Document ID` (e.g. `BH-D103`) or the filename stem;
  it is used for citations and is not unique.
- **Claim ID**: `<sha256[:12]>:<kind>:<index>`. Kinds: `document`, `relation`, `service_event`, `assessment`,
  `observation`, `plan_requirement`.
- **Encounter key**: `<MRN>|<ENCOUNTER_ID>`, or `<MRN>|U-<date>-<service_type>-<n>` for contacts without an ID.
- **Patient**: keyed by normalised MRN (`ingest.attribute`). Without an MRN, the document must match exactly one
  known patient by name (+ DOB when stated). Otherwise it is **quarantined**: its claims keep `patient_mrn` NULL,
  it gets a `quarantine` row (`no_patient_identity`, `ambiguous_patient`, `multi_patient` or `mrn_mismatch`), and it
  takes part in no patient's reconciliation. Identity the **text** states outranks the extraction
  (`ingest.text_identity`, no LLM):
  - `multi_patient`: the text names more than one patient. That is more than one distinct `MRN`-labelled value, or an
    MRN table column (`MRN | …` header row) with several values, or a patient-name column (`Patient` / `Name` /
    `Member` … header cell, exact match) with several names. The extraction holds one patient per document, so no
    claim is attributed. A patient banner line (`Patient: X | DOB: … | MRN: …`) is not a table header.
  - An explicit correction on one line (`MRN X corrected/changed/updated to Y`, `Corrected MRN Y (previously MRN
    X)`) counts as one patient, Y. The document is attributed to Y whichever of the two the extractor reported, and
    the change is recorded in `identifier_changes`. Other documents still carrying X are **not** moved (no merge).
  - `mrn_mismatch`: the extracted MRN is not the one the text prints (compared ignoring case and dashes), or no MRN
    is labelled and the extracted MRN does not appear as a whole token anywhere in the text, or a name-only match
    contradicts the printed MRN.

  Ingest reports quarantines in `stats["quarantined"]`, and `python -m backbone stats` counts them. There is no
  `UNRESOLVED` pool.
- **Re-attribution**: when a re-extraction moves (or quarantines) a document, its former owner is also returned in
  `affected_patients`. `reconcile_patients` then rebuilds that patient from its remaining claims. A patient left
  with no claims and no documents loses its derived rows and its `patients` row. After every ingest,
  `ingest.reattribute` re-runs attribution from the **stored** extraction (latest `extractions` row, never the LLM)
  for quarantined documents and documents matched by name alone. A patient that arrives later can claim a
  quarantined document. A second same-name patient makes a name-only match ambiguous and quarantines it. Only actual
  changes are applied, and they are reported in `stats["reattributed"]`.
- **Pending reconciles** (`pending_reconcile`): every patient whose evidence changes is marked in the **same
  transaction** as the claims. Triggers on `patients` clear the mark when `reconcile.persist()` stamps `reconciled_at`
  or the patient row is deleted, and `cli` also clears it after a successful reconcile. A crash between ingest and
  reconcile therefore cannot leave the abstraction stale. The next `ingest` returns those patients in
  `affected_patients` (and in `pending_from_earlier_runs`), and `reconcile` without `--patient` includes them.

## The results envelope (every operator)

```json
{
  "op": "care|compliance|timeline|compare",
  "params": {"scope": {"...": "..."}, "...": "..."},
  "totals": {"sessions": {"low": 12, "high": 12, "status": "established"}, "minutes": {"low": 585, "high": 595, "status": "bounded"}},
  "groups": [], "facts": [],
  "calculation": ["patient-present minutes = 50 (HG-E101) + ... = 585–595 min"],
  "exclusions": [{"encounter": "HG-E116", "reason": "not attended (no_show)", "records": ["BH-D108", "BH-D112"]}],
  "conflicts": [{"subject": "HG-E115", "field": "patient_present_interval", "candidates": []}],
  "decisions": [{"subject": "HG-E110", "rule": "R3", "outcome": "field_corrected", "reason": "..."}],
  "evidence": [{"doc_id": "BH-D103", "file": "...", "record_type": "...", "passages": [{"lines": "7", "quote": "..."}]}],
  "notes": [],
  "sql": [{"sql": "SELECT ... WHERE service_date BETWEEN ? AND ?", "params": ["2026-01-05", "2026-01-30"]}]
}
```

## Data flow for a new document

1. `ingest` hashes the file. If the hash is known, it only records the new path.
2. A new hash is extracted, using the cache when possible.
3. `build_claims` verifies quotes, records value grounding (see EXTRACTION.md) and writes claims.
4. The document is attributed (or quarantined). Its MRN and any former owner are marked pending, in the claims'
   transaction. `reattribute` then revisits quarantined and name-matched documents.
5. `reconcile_patients(affected)` deletes and rebuilds only those patients' clinical rows (~4 ms per patient), which
   clears their pending marks.
6. Saved answers are invalidated automatically, because the fingerprint includes every document's sha256.

## Data flow for a question

1. `answer_question` checks `answer_cache` (keyed by question + fingerprint).
2. On a miss, the planner LLM (effort `medium`) returns a `QueryPlan`, validated by Pydantic.
3. `execute_plan` runs it (read-only, milliseconds).
4. The narrator LLM writes from `_slim(results)`, which omits SQL.
5. `postcheck` verifies numbers, document labels and line references.
6. The result is persisted to the cache and `out/answers/`.
