# Reconciliation (`backbone/reconcile.py`, `RULESET_VERSION`)

`reconcile_patient(mrn, claims) -> Result` is **pure**: no database and no LLM. `persist()` replaces that patient's
derived rows inside one transaction. `reconcile_patients` also deletes the `patients` row of an MRN that has no
claims and no documents left (its document was re-attributed or quarantined), so the directory has no empty patients.
Claims of quarantined documents have `patient_mrn` NULL and are never loaded. Every consequential choice calls `res.decide(subject, rule, outcome, reason,
claim_ids)`, and every unresolved disagreement appends to `res.conflicts`. The answers cite these.
`reconcile_patient` first sorts the claims by `claim_id` (the order `load_claims` reads), so its whole output,
decision reasons included, depends on the claim set and never on the order a caller passes it in (#62).
`reconcile_patients` also adds one R1 `attributed_by_<basis>` decision per document of the patient listed in the
evidence-layer table `attribution_notes` (basis `printed_mrn` or `identifier_change`, #71), with the document's claim
ids, so the export and operators show why the document belongs to the patient. A database without that table has none.

## Pipeline inside `reconcile_patient`

1. Attach each claim's document metadata (`signed`, `finality`, `signed_at`).
2. **R0:** drop unverified claims, with a decision. The reason reads the claim's grounding entry: a date that its
   document states nowhere (`unverified_absent`, #52) gives "the date is not stated anywhere in the document (the
   extracted value was inferred)", without repeating the inferred value; a quote that was not located keeps "quote
   not found in source text" (#68).
3. Index relations: field corrections by encounter, plus the scope of each retransmission and copy relation
   (`_scopes`). A copy relation covers only the records it names (#22). A retransmission naming an encounter covers
   that encounter's records; an ID-less event counts as the encounter R1 placed it in. A measurement copy naming a
   form covers that form, plus an ID-less assessment on the form's date. A relation naming only a date covers that
   date. Only a relation naming neither covers its whole document. A correction naming no encounter is an R3
   `correction_not_applied` decision.
4. **R1** `_group_events`: events with an encounter ID form groups. Events without one match a group with the same
   date and service type (and overlapping intervals if both are known) when exactly one candidate exists. A group may
   have several (date, type) pairs: every pair its records state, plus every service type that a `service_type`
   correction of the encounter turns a record's type into (#61; the correcting document's own record excepted, as in
   R3). If there is no such candidate, an ID-less psychotherapy record joins exactly one psychotherapy contact (ID'd
   or not) of another type on that date when their actual contact times overlap, and the type becomes disputed
   (#74). Actual contact times are contact intervals or arrival–departure; a schedule alone never merges. The patient
   cannot attend two sessions at once. Otherwise
   they form a separate `U-` contact (an "unidentified contact" decision). The intervals are every time a record
   states (contact intervals, schedule, arrival–departure when both ends are known), unioned over the group's
   records, so two ID-less sessions known only by disjoint arrival/departure times stay two contacts (#11).
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
     - Resolution is graph reachability over a visited set (`_resolve`, #63), not path enumeration: terminals are
       the reachable values that nothing corrects, plus every reachable value on a cycle. Each applied correction is
       one `field_corrected` decision per record, in breadth-first order.
     - A correction that cannot be applied (field `other`, a value not understood, no record holding the old value)
       is an R3 `correction_not_applied` decision plus an encounter flag, never silently dropped (#10).
     - A correction counts as applied only when it changed a record that contributes (tier 1 or 2). Records that are
       excluded, such as a retransmitted copy, are corrected after that, by applied corrections only. A correction
       whose old value only an excluded record holds is `correction_not_applied` ("held only by excluded record(s)
       ..."), and it does not join `claim_ids` (#64).
     - An applied correction joins the encounter's `claim_ids`, so its passage reaches `evidence` and can be cited,
       unless another claim of the same document in the encounter already cites those lines (#23).
   - Service type and date come from the deciding tier (tier 1, else tier 2), over every `_variants` value, so
     competing service-type corrections count as a disagreement too. A disagreement is never resolved by
     majority or lexical order (#12). It is a `disputed` conflict, and eligibility becomes `uncertain`. Each further
     psychotherapy (date, type) account becomes an alternative row `<key>~<date>-<type>`
     (`_add_identity_alternatives`, R1 `identity_alternative`), so the dispute reaches every week and per-type goal it
     could belong to. The rows share `encounter_id`. `project.aggregate` counts them as at most one session, with
     the largest of their minutes. Alternatives of an unidentified `U-` contact share the key before `~`. R7 does
     not compare them with each other. The representative row is the first psychotherapy account, or the first
     account if there is none (never a majority pick). A non-psychotherapy account gets a row too, with
     `eligible = 'no'` and no minutes. Only a goal that counts its type sees that row (#48).
   - Attendance (R4): the first tier with a known yes/no decides. Yes and no in the same tier gives `disputed`.
   - Presence: tier-1 `patient_present` votes; not attended implies not present.
   - Eligibility (R5): `yes` if psychotherapy (`THERAPY_TYPES`), attended and present. `no` with a reason. Otherwise
     `uncertain`.
   - Minutes (R6): candidate patient-present interval sets come from each tier-1 record's explicit contact
     intervals, or else its (corrected) arrival–departure. If there are none, an `attended_full` scheduled
     interval is used.
     - Non-therapeutic intervals are reconciled per kind (#13). A record that states none of a kind is silent, not
       a "no break" account; this is why a note's break subtracts from a register's arrival–departure. The first
       tier that states a kind decides it (R4 `exclusion_tier`). Different sets of one kind from records of that
       tier are alternative accounts, never unioned (R6 `exclusions_disputed`). Different kinds all apply.
     - The scheduled interval is reconciled (#66), not taken from the first record. The first tier that states a
       schedule decides it. Different schedules from that tier give a `scheduled_interval` conflict and a flag.
       A lower tier's different schedule is an R4 `schedule_tier` decision. As the presence account of
       `attended_full` records, each record uses its own schedule, else every deciding schedule, so disagreeing
       schedules give `disputed` bounds. The unknown-minutes upper bound is the largest valid deciding schedule
       minus the least exclusion.
     - Each candidate minus each exclusion account gives minutes. One candidate and one account is `established`.
       Otherwise the result is `disputed`, with `[min, max]` bounds and a conflict. No candidate is `unknown`, with
       `[0, scheduled − least exclusions]`.
     - A scheduled, contact or arrival–departure interval that is inverted, overnight or incomplete is never
       dropped silently (#17). It gives `unknown` with a flag, and no upper bound unless a valid schedule gives one.
       An invalid exclusion gives `unknown` with a low bound of 0.
     - Stated minutes outside the bounds produce a flag (cross-check only).
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
   - R9 `goal_not_restated` (#49): when a later requirement for the same metric, starting inside a goal's effective
     period, does not restate that goal (same metric, counted types and period), the goal may have lapsed. One
     decision per goal, at the first revision that omits it. The projection evaluates the goal both ways.
8. **R9 note:** an eligible session on a plan's first effective day that started before the plan signature is
   counted and logged (effectivity is by date).
9. **R8** `_assessments`: grouped by (instrument, completed date), split by distinct form IDs. Copies
   (`is_copy_of_earlier`, or a document with a `copies_measurement` relation) are listed in `copy_claim_ids`, not
   as new assessments. Different scores give a `disputed` status plus a conflict.
10. `_observations`: deduplicated by (date, domain, document label, normalised quote).

## Plan semantics (in `project.py`, because they are evaluated at query time)

- `requirement_sets_on(reqs, day)`: active requirements per **goal** (`goal_key`: metric, counted types and
  period, #49 and #50). For each goal, those with the **latest effective_start** win: a revision supersedes, by
  effective date.
  - Different goals are independent, whichever documents state them: ≥ 2 individual and ≥ 1 group sessions, or a
    weekly and a monthly goal.
  - Identical per-document sets restated by other documents count once.
  - Different sets for one goal from different documents with the same latest start date are a conflict: every
    alternative is returned. The document is identified by claim id (sha256 prefix), not by label.
  - Suppose a later requirement for the same metric does not restate a goal (a revision restates the individual
    goal but not the group goal). That goal is then an alternative: the sets with and without it are both
    returned, with a note. Agreement gives the verdict, disagreement gives UNDETERMINED (DECISIONS 24).
- `weekly_compliance`: whole-week totals (only days covered by some plan) are evaluated against **each** requirement
  set in effect that week. Agreement gives the verdict; disagreement gives UNDETERMINED with a note. A partial
  segment is never compared with a weekly goal.
  - Each requirement is counted over its **own** `counted_types`. A requirement whose types differ from the set's
    union carries its own `counted_service_types`.
  - A period other than `week_mon_sun` is UNDETERMINED ("unsupported").
- `evaluate_requirement`: for monotone comparators, MET if the goal holds at both bounds, NOT_MET at neither, else
  UNDETERMINED. For `==`: MET only when low = high = threshold, NOT_MET when the threshold is outside [low, high],
  else UNDETERMINED. An unbounded high (`None`) is ∞.
  - The projection counts R5-eligible sessions: psychotherapy, attended, patient present. So
    `requires_patient_present = 1` is enforced by eligibility.
  - A set that also counts non-psychotherapy types selects those rows too (`counting_rows`, #48). Attended and
    present counts `yes`. Not attended or not present counts `no`. Anything else, or a disputed date or type, is
    `uncertain`. Sessions and days goals over such types are judged exactly. Their minutes are unknown, because
    reconciliation computes psychotherapy minutes only. So a minutes goal over such types stays a lower bound.
  - When a goal counts sessions or days without requiring presence, the projected total is only a lower bound. Its
    high becomes ∞, with a "lower bound only" reason.
  - An unsupported metric (`other`) is UNDETERMINED. Its evaluation still names `metric` and `goal` (#72).
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
