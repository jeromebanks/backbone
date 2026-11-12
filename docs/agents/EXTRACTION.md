# Extraction

## Contract (`backbone/schema.py`)

One LLM call per document returns an `Extraction`:

| Part | Purpose | Key fields |
|---|---|---|
| `document` | how much weight this record can carry | `document_id`, `signed`, `signed_at`, `received_at`, `finality` (final/draft/unknown), patient name/MRN/DOB, `relations[]` |
| `relations[]` | cross-record links **by keys the text states** | `type` ∈ corrects_field, retransmits_original, copies_measurement, companion_record, references; `encounter_id`, `field`, `old_value`, `new_value`, `form_id`, `original_date` |
| `service_events[]` | one per service/appointment the document informs | `encounter_id` vs `related_encounter_id`, `service_type`, `evidence_type`, `disposition`, `patient_present`, `scheduled`, `patient_arrival/departure`, `patient_contact_intervals[]`, `nontherapeutic_intervals[]` (break, disconnection, patient_absent), `stated_minutes`, `quotes[]` |
| `assessments[]` | instruments (PHQ-9 …) | `total_score`, `item_scores`, `completed_date` (not the import date), `form_id`, `is_copy_of_earlier` |
| `observations[]` | symptom/functioning/safety/progress statements | `date`, `domain`, `source` (patient_report, clinician_observation, clinician_assessment, collateral_report, measurement), `statement`, `quote` |
| `plan_requirements[]` | measurable participation goals | `metric` (therapy_days, patient_present_minutes, sessions), `comparator`, `threshold`, `period`, counted/excluded service types, `requires_patient_present`, effective dates |

`evidence_type` matters: one document can hold several record types for the same encounter. D106 has a note plus
a platform log; D112 has a draft template plus a billing row. Each record type becomes its own event.

## Prompt rules (`extract.py: SYSTEM`)

- Literal extraction only. No inference from other documents, no conflict resolution, **no computed durations**.
- Times `HH:MM` 24h, dates `YYYY-MM-DD`. Verbatim short quotes. Several quotes rather than joined fragments.
- A call or notice *about* an appointment produces two events: the appointment's status (with its encounter ID), and
  the call itself (`encounter_id: null`, `related_encounter_id` set).
- The prompt must stay generic. Its examples use invented times and scores, never values from `documents/`.

## Quote verification (`evidence.py`)

`DocumentIndex` normalises whitespace, dash and quote variants, and case, keeping a map back to original line numbers.
`locate()` tries, in order: an exact/normalised match, then ellipsis-joined fragments in order, then a fuzzy
same-length window (≥ 0.92 similarity). Spans go into `claims.evidence` as `{quote, line_start, line_end, match}`.
`claims.verified = 1` only if every quote was found. Unverified claims are dropped by R0. In this corpus 254 claims
were extracted, with 0 fuzzy matches and 0 unverified.

## Cache

`cache/extractions/<sha256>.<EXTRACTOR_VERSION>.<model>.json` holds `{sha256, filename, meta, extraction}`.
`extract_document` reads this before calling the LLM. The cache ships with the repo, so a clean checkout rebuilds
the DB with **0 LLM calls**. Changing the prompt or schema requires bumping `EXTRACTOR_VERSION`. That invalidates
every entry: the 31 documents cost ~$1.38 at list price and take ~60 s at concurrency 8.

## LLM backends (`llm.py`)

- `claude-cli` (default): `claude -p --model claude-opus-5-5 --output-format json --json-schema <schema> --tools ""
  --system-prompt … --no-session-persistence --strict-mcp-config --setting-sources "" --effort high`, run from a
  temp cwd. It reads `structured_output`, `usage` and `total_cost_usd` (the list-price equivalent) from the JSON
  envelope. Authentication is the user's Claude subscription login.
- `anthropic-api`: `client.beta.messages.stream` with `output_config={"effort", "format": json_schema}` and
  server-side `fallbacks="default"`, checking `stop_reason == "refusal"`. **Never exercised** (no key was available).
- `complete_json` sanitises the schema (strips `discriminator`), validates with Pydantic, and retries twice on
  transport or validation errors. A schema rejection is not retried.
- Ingest runs extraction in a thread pool (`BACKBONE_CONCURRENCY`, default 6). A failed document is logged in the
  stats and does not stop the run.

## Known extraction gaps

These fields are not in the schema, so no question that needs them can be answered (see
`docs/CLINICAL_QA_DESIGN.md` §5C). Verified against the current database: the authorization letter BH-D001 yields
only a document-level claim, and the BH-D112 charge has no code, units or amount.

- **Authorizations:** service, quantity, unit definition, period, authorization ID.
- **Charges:** billing code, units, amount, and billable-vs-goal-countable (family therapy without the patient is
  usually billable but does not count toward the plan's participation goal).
- **Treatment-plan goals and objectives** (qualitative), and links from sessions to goals.
- **Interventions** per session.
- **Structured risk assessment items** per encounter.
- **Diagnoses, medications and changes, vitals.**
- **Discharge and aftercare plans.**
- **Richer plan requirements:** frequency per service type, deadlines, assessment cadence.

Add them together under **one** `EXTRACTOR_VERSION` bump, after the gold set covers them, to pay for re-extraction
once (and only for the affected document types).

## Measured

8,318 input tokens per document (≈90% fixed prompt + schema), 1,574 output, 13.2 s mean / 19.5 s p95, $0.045 list
per document.
