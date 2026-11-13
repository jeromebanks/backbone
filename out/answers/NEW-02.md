# NEW-02

> Which weeks met the therapy-day goal but not the minute goal?

**One week clearly fits: 2026-01-05 to 2026-01-11.** That week had 3 therapy days, which meets the goal of 3 or more. It had 140 patient-present minutes, which falls short of the goal of 150 or more. A second week, 2026-01-26 to 2026-01-30, met the therapy-day goal, but whether it met the minute goal is **UNDETERMINED**.

The goal comes from the signed plan: "at least 3 therapy days and at least 150 minutes of patient-present therapy in each Monday–Sunday week." Individual, group and family therapy all count toward minutes (BH-D003 L12).

| Week | Therapy days (goal ≥3) | Minutes (goal ≥150) | Days goal | Minutes goal | Overall |
|---|---|---|---|---|---|
| 2026-01-05 – 01-11 | 3 | 140 (50 HG-E101 + 45 HG-E102 + 45 HG-E104) | MET | NOT_MET | NOT_MET |
| 2026-01-12 – 01-18 | 2 | 120 | NOT_MET | NOT_MET | NOT_MET |
| 2026-01-19 – 01-25 | 3 | 180 | MET | MET | MET |
| 2026-01-26 – 01-30 (partial) | 3 | [145–155] | MET | UNDETERMINED | UNDETERMINED |

**What the record does not settle**
- **Week of 2026-01-26:** two clinical notes disagree on how long the patient was present for HG-E115. BH-D110 gives 09:00–09:50 (50 min) and BH-D111 gives 09:10–09:50 (40 min). Neither note corrects the other, so the session is carried as 40–50 minutes. That puts the week's total at 145–155, on both sides of the 150-minute goal. If the 40-minute figure is right, this week would also be "days met, minutes not met."
- This week is also only partly inside the period asked about: 5 of 7 days (2026-01-26 to 2026-01-30). Sessions later that week are not counted.

**Excluded from the counts (relevant to the two weeks above)**
- **Week of 2026-01-05:**
  - HG-E103 (individual therapy, 2026-01-08) was a no-show.
  - An outreach call on 2026-01-08 is not a therapy service.
- **Week of 2026-01-26:**
  - HG-E116 (group, 2026-01-27) was a no-show. A draft/template and a billing row in BH-D112 suggest attendance, but they were not accepted as attendance evidence.
  - HG-E117 (individual, 2026-01-28) was cancelled by the patient.
  - An outreach call on 2026-01-27 and medication management HG-E120 on 2026-01-30 are not therapy services.

Line citations are given only for the plan, because no line-level evidence was provided for the encounter records.

## Not settled by the record

- Week of 2026-01-26: minute total is 145–155 against the 150 goal because the two notes disagree on HG-E115's patient-present time (BH-D110: 50 min, BH-D111: 40 min)
- Week of 2026-01-26 was checked only through 2026-01-30 (5 of 7 days)

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
- cited documents not in the computed results: none
- line references outside the evidence passages: none

## Evidence passages

| Doc | Lines | File | Record | Quote |
|---|---|---|---|---|
| BH-D003 | 12 | signed_treatment_plan_jan05.txt | plan_requirement | Patient-present individual, group, and family therapy contribute to the minute goal. |

_timings (ms): {'plan_llm': 4888, 'execute': 5.28, 'narrate_llm': 14579, 'total': 19473}; LLM calls: 2, tokens in/out: 13346/1594, list-price cost $0.106; cached: False_