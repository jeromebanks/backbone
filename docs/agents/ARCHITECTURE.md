# Architecture

## Layers

| Layer | Produced by | Tables | Mutability |
|---|---|---|---|
| Source | the filesystem | `documents` (sha256 PK, `doc_label`, `paths` JSON, `text`, `patient_mrn`) | append; a duplicate file adds a path; `patient_mrn` is set by (re-)attribution |
| Extraction | `extract.py` (LLM) | `extractions` (raw JSON, latency, tokens, cost) + `cache/extractions/*.json` | keyed by (sha256, `EXTRACTOR_VERSION`, model) |
| Evidence | `ingest.build_claims` | `claims` (one row per assertion; `payload` JSON; `evidence` = verified spans + a grounding entry; `verified`) | not append-only: a document's claims are deleted and rewritten when it is (re-)extracted; `patient_mrn` is rewritten by (re-)attribution; never written by reconcile |
| Attribution | `ingest.attribute_document`, `ingest.reattribute` | `quarantine` (unattributable documents), `identifier_changes` (MRN corrections stated in text), `attribution_notes` (why a document was attributed other than by its extracted MRN) | rewritten per document whenever it is (re-)attributed |
| Bookkeeping | `ingest` (mark) / `reconcile.persist` (clear, by trigger) | `pending_reconcile` (patients whose evidence changed and are not yet reconciled) | marked in the claims' transaction |
| Clinical | `reconcile.py` | `patients`, `encounters`, `encounter_intervals`, `plan_requirements`, `assessments`, `observations`, `decisions`, `conflicts` | **derived**; deleted and rebuilt per patient |
| Projection | `project.py` + view `v_encounter_week` | none persisted (computed per query) | pure |
| Answers | `answer.py` | `answer_cache`, `out/answers/*.json|md` | keyed by question + fingerprint |
| Ops | `cli.py` | `run_log` | append |

## Module map

```
schema.py      Pydantic extraction contract (DocumentInfo, ServiceEvent, Relation, Assessment, Observation, PlanRequirement)
extract.py     SYSTEM prompt, extract_document() with file cache
llm.py         complete_json(): claude-cli | anthropic-api backends, schema sanitising, retries, usage capture
evidence.py    DocumentIndex.locate(quote) → line span (exact | normalized | fragments | fuzzy ≥0.92 with digits kept | missing);
               ground_values (is each payload value stated in the claim's own quote / the document / nowhere)
ingest.py      discover → sha256 → documents → parallel extract → build_claims → attribute or quarantine →
               reattribute → pending_reconcile → affected patient MRNs
intervals.py   minute-resolution interval algebra: normalize, subtract, intersect, total, overlaps
reconcile.py   reconcile_patient(mrn, claims) → Result (pure) ; persist() ; reconcile_patients()
project.py     select_encounters, aggregate (bounds), requirement_sets_on, weekly_compliance, plan_change_dates,
               evaluate_requirement, consecutive_runs  ← the ONLY place clinical numbers are computed
query.py       Scope, CareStep/ComplianceStep/TimelineStep/CompareStep, QueryPlan, execute_plan()
operators.py   care, compliance, timeline, compare → envelope; evidence/decision/conflict lookups
dsl.py         fluent builder → QueryPlan
summary.py     compact readout for `plan --summary`
answer.py      directory(), planner → execute → narrator → postcheck() gate (one regeneration); answer cache keyed by
               fingerprint() (content hash); verify_answers()
paths.py       safe_output_path(): output file names from question IDs and MRNs
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
- **Patient**: keyed by normalised MRN (`ingest.attribute_document`). Without an extracted MRN, the document must
  match exactly one known patient by name (+ DOB when stated). If the name matches no known patient (or there is no
  name) and the text prints exactly one MRN, that MRN is used and the basis is recorded in `attribution_notes`
  (`printed_mrn`, #55), unless it belongs to a known patient recorded under another name (`mrn_mismatch`). Otherwise it is **quarantined**: its claims keep `patient_mrn` NULL,
  it gets a `quarantine` row (`no_patient_identity`, `ambiguous_patient`, `multi_patient` or `mrn_mismatch`), and it
  takes part in no patient's reconciliation. Identity the **text** states outranks the extraction
  (`ingest.text_identity`, no LLM):
  - `multi_patient`: the text names more than one patient. That is more than one distinct `MRN`-labelled value, or an
    MRN table column (`MRN | …` header row) with several values, or a patient-name column (`Patient` / `Name` /
    `Member` … header cell, exact match) with several names. Tables may be pipe-, tab- or whitespace-aligned; an
    aligned table counts only when every header cell is a known column heading, so an aligned key/value block is
    not one (#54). Or a free-text attendee line (`Attendees:`, `Patients present:`, `Group members:` …) lists two or
    more person names not annotated as staff or family (a credential such as `LCSW`, or a role such as `(partner)`).
    `Participants:` and `Present:` lines are not read as patient lists: family and staff are listed there. The
    extraction holds one patient per document, so no claim is attributed. A patient banner line
    (`Patient: X | DOB: … | MRN: …`) is not a table header.
  - An explicit correction on one line (`MRN X corrected/changed/updated to Y`, `Corrected MRN Y (previously MRN
    X)`) counts as one patient, Y. The document is attributed to Y whichever of the two the extractor reported, and
    the change is recorded in `identifier_changes` (not for a `multi_patient` document). Every other document whose
    MRN is X then resolves to Y as well (`ingest.resolve_identifier`, #53): chains X→Y→Z are followed; a fork
    (X→Y and X→Z) or a cycle resolves nothing and quarantines the document as `ambiguous_patient` with the candidates.
    A moved document gets an `attribution_notes` row (`identifier_change`, naming the stating document and line).
    The recorded corrections depend only on documents' texts, so the result does not depend on ingest order.
  - `mrn_mismatch`: the extracted MRN is not the one the text prints (compared ignoring case and dashes), or no MRN
    is labelled and the extracted MRN does not appear as a whole token anywhere in the text, or a name-only match
    contradicts the printed MRN.

  Ingest reports quarantines in `stats["quarantined"]`, and `python -m backbone stats` counts them. There is no
  `UNRESOLVED` pool.
- **Re-attribution**: when a re-extraction moves (or quarantines) a document, its former owner is also returned in
  `affected_patients`. `reconcile_patients` then rebuilds that patient from its remaining claims. A patient left
  with no claims and no documents loses its derived rows and its `patients` row. After every ingest,
  `ingest.reattribute` re-runs attribution from the **stored** extraction (latest `extractions` row, never the LLM)
  for quarantined documents, documents matched by name alone, and documents an MRN correction may move (owned by,
  or extracted with, a corrected MRN, or moved by a correction before), including documents of the same batch. A
  patient that arrives later can claim a quarantined document. A second same-name patient makes a name-only match
  ambiguous and quarantines it. Passes repeat to a fixed point (a printed-MRN attribution can create a patient that a
  name-only document then matches). Only actual changes are applied, and they are reported in
  `stats["reattributed"]`; the old and new owners are marked pending, and an old owner left with nothing is removed.
- **Read-only commands** (`directory`, `stats`, `postcheck`, `export`, `plan`, `verify-answers`) open the DB with
  `db.connect_readonly` (`verify-answers --rewrite` too; it writes only the saved answer files): no DDL runs, so the file stays byte-identical (#45). Tables or the week view missing from
  an older DB are created as empty TEMP objects on that connection only. `stats` also reports value grounding per
  kind (`grounding: {date|time|minutes|number: {quote, document, absent}}`) and `pending_reconcile`
  (`patients`, `oldest_marked_at`) (#56).
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
6. Cached answers are invalidated automatically: the fingerprint is a content hash of the documents, committed
   extractions, claims and derived tables (plus the code versions), so any change to what an answer is computed
   from changes it. An identical rebuild does not. Saved answers in `out/answers/` are files and are not changed;
   `verify-answers` shows whether their results still reproduce.

## Data flow for a question

1. `answer_question` checks `answer_cache` (keyed by question + fingerprint). A hit is post-checked again and is
   served only if it passes.
2. On a miss, the planner LLM (effort `medium`) returns a `QueryPlan`, validated by Pydantic.
3. `execute_plan` runs it (read-only, milliseconds).
4. The narrator LLM writes from `_slim(results)`, which omits SQL.
5. `postcheck` checks numbers (including hyphenated compounds) and dates against what the results state, cited
   documents (and `LABEL [sha12]` for shared labels), and that every cited line is inside an evidence passage. On
   failure the narrator is re-run once with the failures fed back. Details: QUERY_DSL.md.
6. A passing result is cached; a still-failing one is returned flagged (banner) and not cached. `answer_file` writes
   `out/answers/` either way.
