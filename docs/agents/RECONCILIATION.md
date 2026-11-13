# Reconciliation (`backbone/reconcile.py`, `RULESET_VERSION`)

`reconcile_patient(mrn, claims) -> Result` is **pure**: no database and no LLM. `persist()` replaces that patient's
derived rows inside one transaction. `reconcile_patients` also deletes the `patients` row of an MRN that has no
claims and no documents left (its document was re-attributed or quarantined), so the directory has no empty patients.
Claims of quarantined documents have `patient_mrn` NULL and are never loaded. Every consequential choice calls `res.decide(subject, rule, outcome, reason,
claim_ids)`, and every unresolved disagreement appends to `res.conflicts`. The answers cite these.

## Pipeline inside `reconcile_patient`

1. Attach each claim's document metadata (`signed`, `finality`, `signed_at`).
2. **R0:** drop unverified claims, with a decision.
3. Index relations: field corrections by encounter, plus the scope of each retransmission and copy relation
   (`_scopes`). A copy relation covers only the records it names (#22). A retransmission naming an encounter covers
   that encounter's records; an ID-less event counts as the encounter R1 placed it in. A measurement copy naming a
   form covers that form, plus an ID-less assessment on the form's date. A relation naming only a date covers that
   date. Only a relation naming neither covers its whole document. A correction naming no encounter is an R3
   `correction_not_applied` decision.
4. **R1** `_group_events`: events with an encounter ID form groups. Events without one match a group with the same
   date and service type (and overlapping intervals if both are known) when exactly one candidate exists. Otherwise
   they form a separate `U-` contact (an "unidentified contact" decision).
5. For each group, `_reconcile_encounter`:
   - `_classify` (R2/R3 evidence tiers): `draft_template`, `billing`, `retransmitted_copy` and documents with
     finality `draft` are excluded with a reason. `clinical_note`, `attendance_record`, `attendance_correction` and
     `platform_log` are tier 1; `schedule_listing`, `administrative_notice` and `other` are tier 2.
   - `_apply_corrections` (R3): a `corrects_field` relation replaces `old_value` with `new_value` **in that field
     only**, on every record of that encounter, including later copies. It never touches the correcting document.
     - Fields: arrival, departure, disposition, contact_interval (`HH:MM–HH:MM`) and service_type. Times compare by
       value, codes by normalised spelling (#10).
     - Corrections form a graph, resolved independently of claim order. A chain (a → b, then b → c) ends at c.
       Competing corrections (a → b and a → c) or a cycle keep every alternative (`Claim.alts`, read through
       `_variants`): minutes become `disputed` bounds and attendance may become `disputed`, with an R3
       `correction_disputed` decision and a `correction:<field>` conflict. Nothing is picked (#9).
     - A correction that cannot be applied (field `other`, a value not understood, no record holding the old value)
       is an R3 `correction_not_applied` decision plus an encounter flag, never silently dropped (#10).
     - An applied correction joins the encounter's `claim_ids`, so its passage reaches `evidence` and can be cited,
       unless another claim of the same document in the encounter already cites those lines (#23).
   - Service type and date: tier-1 majority (conflicts recorded).
   - Attendance (R4): the first tier with a known yes/no decides. Yes and no in the same tier gives `disputed`.
   - Presence: tier-1 `patient_present` votes; not attended implies not present.
   - Eligibility (R5): `yes` if psychotherapy (`THERAPY_TYPES`), attended and present. `no` with a reason. Otherwise
     `uncertain`.
   - Minutes (R6): candidate patient-present interval sets come from each tier-1 record's explicit contact
     intervals, or else its (corrected) arrival–departure. If there are none, an `attended_full` scheduled
     interval is used. Each candidate minus the union of non-therapeutic intervals gives minutes. One distinct
     candidate is `established`; several are `disputed` with `[min, max]` bounds and a conflict. None is `unknown`
     with `[0, scheduled − exclusions]`. Stated minutes outside the bounds produce a flag (cross-check only).
6. **R7** `_overlap_checks`: patient-present sets that overlap across a patient's encounters on one day are flagged.
   A *superseded* pre-correction value that would overlap another encounter is logged as
   `correction_consistent`.
7. `_plans`: one row per (source document sha256, full requirement identity: metric, comparator, threshold, period,
   dates, counted types, patient presence).
   - Requirements from a `draft` document are not operative: an R2 `plan_not_operative` decision, claims kept as evidence.
   - Counted types = the stated list (all psychotherapy if empty) minus `excluded_service_types`. If a type is both
     counted and excluded, the exclusion wins (R9 `excluded_types_removed`). If nothing is left, the result is R9
     `no_counted_types` and the requirement evaluates UNDETERMINED.
   - The same requirement stated by several documents keeps one row per document, plus an R3 `plan_restated` decision.
   - The key stays `mrn|plan|label|metric|start`. Only on a collision (two goals for one metric and start, or two
     documents sharing a label) is a hash of the full identity appended.
8. **R9 note:** an eligible session on a plan's first effective day that started before the plan signature is
   counted and logged (effectivity is by date).
9. **R8** `_assessments`: grouped by (instrument, completed date), split by distinct form IDs. Copies
   (`is_copy_of_earlier`, or a document with a `copies_measurement` relation) are listed in `copy_claim_ids`, not
   as new assessments. Different scores give a `disputed` status plus a conflict.
10. `_observations`: deduplicated by (date, domain, document label, normalised quote).

## Plan semantics (in `project.py`, because they are evaluated at query time)

- `requirement_sets_on(reqs, day)`: active requirements per metric. Those with the **latest effective_start**
  win (a revision supersedes, by effective date).
  - Requirements for one metric from one document apply together (e.g. ≥ 2 individual and ≥ 1 group sessions).
  - Identical per-document sets restated by other documents count once.
  - Different sets from different documents with the same latest start date are a conflict: every alternative is
    returned. The document is identified by claim id (sha256 prefix), not by label.
- `weekly_compliance`: whole-week totals (only days covered by some plan) are evaluated against **each** requirement
  set in effect that week. Agreement gives the verdict; disagreement gives UNDETERMINED with a note. A partial
  segment is never compared with a weekly goal.
  - Each requirement is counted over its **own** `counted_types`. A requirement whose types differ from the set's
    union carries its own `counted_service_types`.
  - A period other than `week_mon_sun` is UNDETERMINED ("unsupported").
- `evaluate_requirement`: for monotone comparators, MET if the goal holds at both bounds, NOT_MET at neither, else
  UNDETERMINED. For `==`: MET only when low = high = threshold, NOT_MET when the threshold is outside [low, high],
  else UNDETERMINED. An unbounded high (`None`) is ∞.
  - The projection counts R5-eligible sessions only: psychotherapy, attended, patient present. So
    `requires_patient_present = 1` is enforced by eligibility.
  - When a goal also counts non-psychotherapy types, or counts sessions or days without requiring presence, the
    projected total is only a lower bound. Its high becomes ∞, with a "lower bound only" reason.
- `compliance` rejects `scope.service_types`: it returns an envelope with `totals.unsupported` and no weeks,
  because the plan's own counting rules define what counts.
- `consecutive_runs(weeks, n)`: `definite` uses NOT_MET weeks only; `possible` also counts UNDETERMINED weeks, which
  gives `depends_on_unresolved`.

## How this corpus exercises the rules

| Encounter | What happens |
|---|---|
| E110 (Jan 19 group) | D102 says departure 11:30; D103 corrects it to 11:15 (R3). D104 is a later resend (excluded, R3). The superseded value would overlap E111 (R7 `correction_consistent`). 10:00–11:15 − break 10:45–11:00 = 60 |
| E115 (Jan 26 individual) | D110 says 09:00–09:50 and D111 says 09:10–09:50. Both signed tier-1 notes, no correction → disputed [40, 50] |
| E116 (Jan 27 group) | D108 register says no-show (tier 1). D112 draft template (excluded, R2) and billing (excluded, R2) |
| E119 (Jan 30 family) | contact 13:15–13:45 with patient_absent 13:00–13:15 → 30. Stated 45 → flag |
| E112 (Jan 21 video) | two contact intervals − disconnection → 45. The platform log is the same encounter |
| E104 (Jan 9 family) | two clinician notes, one group → one session |
| PHQ-9 Jan 16 | D013 primary; D014 import copy (form HG-Q116) → one assessment |

## Planned rules (not implemented)

- **R10, clinicians on encounters.** Carry `clinicians` from tier-1 records onto the encounter, with credentials.
  Merge names only on exact normalised match plus credential. Never merge on surname: "N. Ellis" (desk staff) is not
  "Nora Ellis, LCSW". Needed for `providers` and credential questions.
- **R11, reconciled charges.** Billing rows become `charges` linked to encounters. A charge with
  `attended = no` (e.g. CH-116 for the Jan 27 no-show) is a documentation finding, not attendance evidence (R2 is
  unchanged). Needed for "billed without attendance" and, once codes and units are extracted, for time-supports-code
  checks.
- **Requirement types** (in `project.py`): per-service-type frequency, deadlines, assessment cadence. These use the
  same three-valued bounds logic.

## Adding a rule

1. Write the failing fixture first in `tests/test_rules.py`. `tests/helpers.py` provides `event()`, `relation()`,
   `assessment()`, `doc()` and `with_docs()`, so no DB or LLM is needed.
2. Implement it in `reconcile.py`. Log with `res.decide`, and record disagreements in `res.conflicts`, not silently.
3. Bump `RULESET_VERSION`, run `python -m backbone reconcile`, `pytest`, `verify-answers`, and `python -m backbone.ablation`.
4. Update the rules table in `README.md` and here.
