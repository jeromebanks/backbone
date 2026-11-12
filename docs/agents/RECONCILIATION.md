# Reconciliation (`backbone/reconcile.py`, `RULESET_VERSION`)

`reconcile_patient(mrn, claims) -> Result` is **pure**: no database and no LLM. `persist()` replaces that patient's
derived rows inside one transaction. Every consequential choice calls `res.decide(subject, rule, outcome, reason,
claim_ids)`, and every unresolved disagreement appends to `res.conflicts`. The answers cite these.

## Pipeline inside `reconcile_patient`

1. Attach each claim's document metadata (`signed`, `finality`, `signed_at`).
2. **R0:** drop unverified claims, with a decision.
3. Index relations: field corrections by encounter, plus the sets of retransmitted and copy documents.
4. **R1** `_group_events`: events with an encounter ID form groups. Events without one match a group with the same
   date and service type (and overlapping intervals if both are known) when exactly one candidate exists. Otherwise
   they form a separate `U-` contact (an "unidentified contact" decision).
5. For each group, `_reconcile_encounter`:
   - `_classify` (R2/R3 evidence tiers): `draft_template`, `billing`, `retransmitted_copy` and documents with
     finality `draft` are excluded with a reason. `clinical_note`, `attendance_record`, `attendance_correction` and
     `platform_log` are tier 1; `schedule_listing`, `administrative_notice` and `other` are tier 2.
   - `_apply_corrections` (R3): a `corrects_field` relation replaces `old_value` with `new_value` **in that field
     only**, on every record of that encounter, including later copies. It never touches the correcting document.
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
7. `_plans`: requirements are deduplicated by (metric, comparator, threshold, period, dates, counted types).
8. **R9 note:** an eligible session on a plan's first effective day that started before the plan signature is
   counted and logged (effectivity is by date).
9. **R8** `_assessments`: grouped by (instrument, completed date), split by distinct form IDs. Copies
   (`is_copy_of_earlier`, or a document with a `copies_measurement` relation) are listed in `copy_claim_ids`, not
   as new assessments. Different scores give a `disputed` status plus a conflict.
10. `_observations`: deduplicated by (date, domain, document label, normalised quote).

## Plan semantics (in `project.py`, because they are evaluated at query time)

- `requirement_sets_on(reqs, day)`: active requirements per metric. The one with the **latest effective_start**
  wins (a revision supersedes, by effective date). Identical restatements count once. Different requirements with
  the same latest start date are a conflict: all alternatives are returned.
- `weekly_compliance`: whole-week totals (only days covered by some plan) are evaluated against **each** requirement
  set in effect that week. Agreement gives the verdict; disagreement gives UNDETERMINED with a note. A partial
  segment is never compared with a weekly goal.
- `evaluate_requirement`: MET if the comparator holds at both bounds, NOT_MET at neither, else UNDETERMINED. An
  unbounded high (`None`) is ∞.
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

## Adding a rule

1. Write the failing fixture first in `tests/test_rules.py`. `tests/helpers.py` provides `event()`, `relation()`,
   `assessment()`, `doc()` and `with_docs()`, so no DB or LLM is needed.
2. Implement it in `reconcile.py`. Log with `res.decide`, and record disagreements in `res.conflicts`, not silently.
3. Bump `RULESET_VERSION`, run `python -m backbone reconcile`, `pytest`, `verify-answers`, and `python -m backbone.ablation`.
4. Update the rules table in `README.md` and here.
