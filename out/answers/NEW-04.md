# NEW-04

> Across all patients, who had two consecutive weeks below their treatment-plan requirements, and whose inclusion depends on unresolved documentation?

# Patients with two consecutive weeks below treatment-plan requirements (Jan 5–30, 2026)

**Answer:** One patient, HG-M042, had two consecutive weeks below the plan: the weeks starting 2026-01-05 and 2026-01-12. Both weeks are based on established values, so this finding does not depend on any unresolved documentation. No other patient appears in the results: 1 patient was evaluated, and HG-M042 has a definite run with no possible runs.

**Plan requirement:** At least 3 therapy days and at least 150 patient-present therapy minutes per Monday–Sunday week. Individual, group and family therapy count toward the minutes (BH-D003 L12).

| Week (start) | Counted encounters | Therapy days (goal ≥3) | Minutes (goal ≥150) | Status |
|---|---|---|---|---|
| 2026-01-05 | HG-E101 50 + HG-E102 45 + HG-E104 45 | 3 (MET) | 140 (NOT_MET) | **NOT_MET** |
| 2026-01-12 | HG-E105 75 + HG-E107 45 | 2 (NOT_MET) | 120 (NOT_MET) | **NOT_MET** |
| 2026-01-19 | HG-E110 60 + HG-E111 30 + HG-E112 45 + HG-E113 45 | 3 (MET) | 180 (MET) | MET |
| 2026-01-26 (partial, Jan 26–30 only) | HG-E115 [40–50] + HG-E118 75 + HG-E119 30 | 3 (MET) | 145–155 (UNDETERMINED) | UNDETERMINED |

**Where documentation is unresolved, and why it doesn't affect the answer**
- The only unresolved item is the time the patient was present for HG-E115. One clinical note (BH-D110) says 09:00–09:50 (50 min); another (BH-D111) says 09:10–09:50 (40 min). Neither corrects the other, so the minutes are carried as a range of [40–50]. That leaves the Jan 26 week at 145–155 minutes against a goal of 150, so its status is UNDETERMINED.
- This dispute can't create a second qualifying run, because the week before it (Jan 19) was MET. The Jan 26 week is also only 5 of 7 days, since the requested period ends Jan 30.
- **Interpretation:** No patient's inclusion depends on unresolved documentation. HG-M042 is included on established values alone.

**Records not counted in the two below-requirement weeks**
- **Week of Jan 5:**
  - HG-E103 (Jan 8, individual therapy): no-show (BH-D006, BH-D015).
  - Outreach call on Jan 8: not a psychotherapy service.
- **Week of Jan 12:**
  - HG-E106: medication management (BH-D006, BH-D010).
  - HG-E108 (Jan 15, group therapy): cancelled by the clinic (BH-D006, BH-D016).
  - HG-E109: family collateral contact, not therapy (BH-D006, BH-D012).
  - Administrative, outreach and "other" contacts on Jan 15–16 (BH-D013, BH-D016).
- **Other notes:**
  - HG-E101 took place before the plan was signed (13:05) on the plan's first effective day. It was counted because the plan takes effect by date.
  - In later weeks, a retransmitted copy (BH-D104) and a draft/template note plus a billing row (BH-D112) were excluded as attendance evidence. HG-E110's departure time was corrected from 11:30 to 11:15 based on BH-D103.

Line numbers are only available for BH-D003. The other document IDs above come from the decision and exclusion records, which don't include line numbers.

## Not settled by the record

- HG-E115 patient-present minutes are disputed between BH-D110 (50 min) and BH-D111 (40 min), so the week of 2026-01-26 is UNDETERMINED (145–155 vs goal ≥150). This does not affect any two-week run.

## How this was computed

```
QueryPlan: Across all patients, who had two consecutive weeks below their treatment-plan requirements, and whose inclusion depends on unresolved documentation?
  1. compliance(patients=all, 2026-01-05..2026-01-30, include_excluded, consecutive_below=2)
```

**compliance**

- HG-M042 week 2026-01-05: 2026-01-05..2026-01-11: days 3, minutes 140 -> patient_present_minutes NOT_MET; therapy_days MET => NOT_MET
- HG-M042 week 2026-01-12: 2026-01-12..2026-01-18: days 2, minutes 120 -> patient_present_minutes NOT_MET; therapy_days NOT_MET => NOT_MET
- HG-M042 week 2026-01-19: 2026-01-19..2026-01-25: days 3, minutes 180 -> patient_present_minutes MET; therapy_days MET => MET
- HG-M042 week 2026-01-26: 2026-01-26..2026-01-30: days 3, minutes 145–155 -> patient_present_minutes UNDETERMINED; therapy_days MET => UNDETERMINED

## Post-check

- numbers in the answer not found in computed results: none
- cited documents not in the corpus: none
- line references outside the evidence passages: none

## Evidence passages

| Doc | Lines | File | Record | Quote |
|---|---|---|---|---|
| BH-D003 | 12 | signed_treatment_plan_jan05.txt | plan_requirement | Patient-present individual, group, and family therapy contribute to the minute goal. |

_timings (ms): {'plan_llm': 3324, 'execute': 6.04, 'narrate_llm': 25801, 'total': 29131}; LLM calls: 2, tokens in/out: 13171/3567, list-price cost $0.143; cached: False_