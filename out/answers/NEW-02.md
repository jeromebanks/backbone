# NEW-02

> Which weeks met the therapy-day goal but not the minute goal?

**Answer:** For patient HG-M042, only the **week of 2026-01-05 to 2026-01-11** clearly met the therapy-day goal but not the minute goal. It had 3 therapy days against a goal of at least 3, and 140 minutes against a goal of at least 150.

The **week of 2026-01-26** also met the therapy-day goal (3 days). Whether it met the minute goal can't be settled from the record: the minutes fall between 145 and 155, which straddles the 150-minute threshold.

The goal comes from the signed treatment plan: "at least 3 therapy days and at least 150 minutes of patient-present therapy in each Monday–Sunday week." Individual, group and family therapy count toward the minutes (BH-D003 L12).

| Week | Therapy days (goal ≥3) | Minutes (goal ≥150) | Overall |
|---|---|---|---|
| 01-05 to 01-11 | 3 – MET | 140 (50 HG-E101 + 45 HG-E102 + 45 HG-E104) – NOT MET | **NOT_MET (days met, minutes not)** |
| 01-12 to 01-18 | 2 – NOT MET | 120 – NOT MET | NOT_MET (both missed) |
| 01-19 to 01-25 | 3 – MET | 180 – MET | MET |
| 01-26 to 01-30 (partial) | 3 – MET | 145–155 – UNDETERMINED | **UNDETERMINED** |

**What the record does not settle**
- **Week of 01-26:** Two clinical notes give different times for when the patient was present in HG-E115. BH-D110 says 09:00–09:50 (50 min) and BH-D111 says 09:10–09:50 (40 min). Neither note corrects the other, so the session is counted as 40 to 50 minutes. With HG-E118 (75) and HG-E119 (30), the week totals 145–155. If the 40-minute time is right, this week also fits "days met, minutes not." If the 50-minute time is right, the week met both goals.
- Only 5 of the 7 days in that week (01-26 to 01-30) fall inside the review period, so contacts on 01-31 or 02-01 were not looked at.

**Records not counted (relevant to these weeks)**
- **Week of 01-05:**
  - HG-E103 (individual therapy, 01-08) was a no-show (BH-D006, BH-D015).
  - An outreach call on 01-08 is not a therapy service.
- **Week of 01-26:**
  - HG-E116 (group therapy, 01-27) was a no-show. A draft template and a billing row in BH-D112 show it as attended, but neither counts as attendance evidence.
  - HG-E117 (01-28) was cancelled by the patient.
  - HG-E120 (01-30, medication management) and an outreach call on 01-27 are not therapy services.

## Not settled by the record

- Week of 2026-01-26: the minute goal can't be settled (145–155 vs ≥150) because two notes give different patient-present times for HG-E115 (BH-D110: 50 min; BH-D111: 40 min).

## How this was computed

```
QueryPlan: Which weeks met the therapy-day goal but not the minute goal?
  1. compliance(patients=['HG-M042'], 2026-01-05..2026-01-30)
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

_timings (ms): {'plan_llm': 2676, 'execute': 7.51, 'narrate_llm': 19147, 'total': 21830}; LLM calls: 2, tokens in/out: 23485/2509, list-price cost $0.069; cached: False_