# DEV-03

> For each week, did the delivered therapy meet the goal documented in Rowan’s treatment plan? State the goal, the relevant therapy-day and minute totals, and whether it was met, not met, or cannot be determined from the current record.

**Short answer:** Of the four weeks from 2026-01-05 to 2026-01-30, Rowan met the treatment-plan goal in one week. Two weeks fell short, and the last week can't be decided from the current record.

**Goal (signed treatment plan BH-D003):** "at least 3 therapy days and at least 150 minutes of patient-present therapy in each Monday–Sunday week." Patient-present individual, group and family therapy count toward the minutes (BH-D003 L12). A week meets the goal only if both parts are met.

| Week | Therapy days (goal ≥ 3) | Patient-present minutes (goal ≥ 150) | Encounters counted | Overall |
|---|---|---|---|---|
| 2026-01-05 – 01-11 | 3: met | 140: not met (50 + 45 + 45) | HG-E101, HG-E102, HG-E104 | **NOT MET** |
| 2026-01-12 – 01-18 | 2: not met | 120: not met (75 + 45) | HG-E105, HG-E107 | **NOT MET** |
| 2026-01-19 – 01-25 | 3: met | 180: met (60 + 30 + 45 + 45) | HG-E110, HG-E111, HG-E112, HG-E113 | **MET** |
| 2026-01-26 – 01-30 (partial week) | 3: met | 145–155: undetermined ([40–50] + 75 + 30) | HG-E115, HG-E118, HG-E119 | **CANNOT BE DETERMINED** |

**Why the last week is undetermined**
- Two signed clinical notes give different patient-contact times for HG-E115, and neither corrects the other:
  - BH-D110 gives 09:00–09:50, which is 50 min.
  - BH-D111 gives 09:10–09:50, which is 40 min.
- Because of this, the week's minutes are carried as a range of 145–155, which falls on both sides of the 150-minute goal. The therapy-day part of the goal (3 days) is met.
- Only 2026-01-26 to 2026-01-30 is inside the period you asked about (5 of 7 days). Any therapy later that week is not counted here.
- To settle it, someone would need to reconcile the HG-E115 contact time.

**How the records were handled**
- **HG-E101:** This session started before the plan was signed (2026-01-05T13:05), on the plan's first effective day. It was counted because the plan takes effect by date.
- **HG-E110:** The departure time was changed from 11:30 to 11:15 based on an explicit correction (BH-D103). BH-D104 is a retransmitted copy, so it was not used as independent evidence.
- **HG-E116 (2026-01-27, group):** Counted as a no-show. BH-D112 says the patient "attended_full," but that document is a draft/template and a billing row, so it was excluded as attendance evidence.

**Encounters left out of the totals**
- **Not attended:**
  - HG-E103 on 01-08 (no-show)
  - HG-E108 on 01-15 (clinic cancelled)
  - HG-E116 on 01-27 (no-show)
  - HG-E117 on 01-28 (patient cancelled)
- **Not psychotherapy services:**
  - Medication management: HG-E106 (01-13) and HG-E120 (01-30)
  - Family collateral contact: HG-E109 (01-16)
  - Care coordination: HG-E114 (01-23)
  - Outreach calls on 01-08, 01-15 and 01-27
  - Administrative and other entries on 01-15 and 01-16

This review only compares delivered therapy against the plan's participation goal. It does not assess clinical progress or outcomes.

## Not settled by the record

- Week of 2026-01-26: patient-present minutes are 145–155 against the ≥150 goal because the HG-E115 contact interval is disputed (BH-D110: 09:00–09:50, 50 min; BH-D111: 09:10–09:50, 40 min).

## How this was computed

```
QueryPlan: For each week, did the delivered therapy meet the goal documented in Rowan’s treatment plan? State the goal, the relevant therapy-day and minute totals, and whether it was met, not met, or cannot be determined from the current record.
  1. compliance(patients=['HG-M042'], 2026-01-05..2026-01-30, include_excluded)
```

**compliance**

- HG-M042 week 2026-01-05: 2026-01-05..2026-01-11: days 3, minutes 140 -> patient_present_minutes NOT_MET; therapy_days MET => NOT_MET
- HG-M042 week 2026-01-12: 2026-01-12..2026-01-18: days 2, minutes 120 -> patient_present_minutes NOT_MET; therapy_days NOT_MET => NOT_MET
- HG-M042 week 2026-01-19: 2026-01-19..2026-01-25: days 3, minutes 180 -> patient_present_minutes MET; therapy_days MET => MET
- HG-M042 week 2026-01-26: 2026-01-26..2026-01-30: days 3, minutes 145–155 -> patient_present_minutes UNDETERMINED; therapy_days MET => UNDETERMINED

## Post-check

- numbers in the answer not found in computed results: none
- cited documents not in the corpus: none
- cited documents not in the computed results: none
- line references outside the evidence passages: none

## Evidence passages

| Doc | Lines | File | Record | Quote |
|---|---|---|---|---|
| BH-D003 | 12 | signed_treatment_plan_jan05.txt | plan_requirement | Patient-present individual, group, and family therapy contribute to the minute goal. |

_timings (ms): {'plan_llm': 3895, 'execute': 1.5, 'narrate_llm': 15588, 'total': 19484}; LLM calls: 2, tokens in/out: 13560/1858, list-price cost $0.113; cached: False_