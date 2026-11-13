# DEV-03

> For each week, did the delivered therapy meet the goal documented in Rowan’s treatment plan? State the goal, the relevant therapy-day and minute totals, and whether it was met, not met, or cannot be determined from the current record.

# Rowan (HG-M042): weekly therapy vs. treatment-plan goal, Jan 5–30, 2026

**Short answer:** Rowan met the goal in 1 week and missed it in 2. One week can't be determined from the current record.

- **Met:** week of Jan 19.
- **Not met:** weeks of Jan 5 and Jan 12.
- **Cannot be determined:** week of Jan 26, because two notes give different session times.

**The goal:** The signed treatment plan sets a "Local treatment participation goal: at least 3 therapy days and at least 150 minutes of patient-present therapy in each Monday–Sunday week" (BH-D003 L12). Individual, group and family therapy all count toward the minute goal (BH-D003 L12).

| Week | Therapy days (goal ≥ 3) | Patient-present minutes (goal ≥ 150) | Encounters counted | Status |
|---|---|---|---|---|
| Jan 5–11 | 3 (met) | 140 = 50 + 45 + 45 (not met) | HG-E101, HG-E102, HG-E104 | **Not met** |
| Jan 12–18 | 2 (not met) | 120 = 75 + 45 (not met) | HG-E105, HG-E107 | **Not met** |
| Jan 19–25 | 3 (met) | 180 = 60 + 30 + 45 + 45 (met) | HG-E110, HG-E111, HG-E112, HG-E113 | **Met** |
| Jan 26–30 (partial) | 3 (met) | 145–155 = [40–50] + 75 + 30 (undetermined) | HG-E115, HG-E118, HG-E119 | **Cannot be determined** |

## What the record doesn't settle
- **Week of Jan 26, minutes:** Two clinical notes for HG-E115 give different patient-contact times: 09:00–09:50 (50 min) in BH-D110 and 09:10–09:50 (40 min) in BH-D111. Neither note corrects the other, so the week's total is carried as 145–155 minutes. That range runs from below to above the 150-minute goal. The day goal (3 days) is met either way.
- **Partial week:** Only Jan 26–30 (5 of 7 days) falls inside the period you asked about. Any therapy on Jan 31–Feb 1 wasn't evaluated.
- **Week of Jan 5:** HG-E101 started before the plan was signed (2026-01-05T13:05). It was still counted because the plan takes effect by date, starting Jan 5.

## What was excluded and why
- **Missed sessions (no-show or cancelled):**
  - HG-E103, Jan 8: no-show (BH-D006, BH-D015)
  - HG-E108, Jan 15: group cancelled by the clinic (BH-D006, BH-D016)
  - HG-E116, Jan 27: group no-show (BH-D108, BH-D112)
  - HG-E117, Jan 28: cancelled by the patient (BH-D108)
- **Not psychotherapy:**
  - Medication management: HG-E106, Jan 13 (BH-D006, BH-D010) and HG-E120, Jan 30 (BH-D114)
  - Family collateral contact: HG-E109, Jan 16 (BH-D006, BH-D012)
  - Care coordination: HG-E114, Jan 23 (BH-D109)
  - Outreach calls on Jan 8, 15 and 27 (BH-D015, BH-D016, BH-D108)
  - Administrative or other contacts on Jan 15–16 (BH-D013, BH-D016)
- **Records not accepted as evidence:**
  - HG-E116: BH-D112 says "attended_full," but it is a draft/template and a billing row, so it doesn't count as attendance evidence. The no-show stands.
  - HG-E110: BH-D104 is a retransmitted copy, so it isn't independent evidence. A correction (BH-D103) changed the departure time in BH-D102 and BH-D104 from 11:30 to 11:15. This leaves 60 counted minutes.

The statuses above only compare documented attendance and minutes with the plan's participation goal. They say nothing about Rowan's clinical progress.

## Not settled by the record

- HG-E115 (week of Jan 26): BH-D110 gives 09:00–09:50 (50 min) and BH-D111 gives 09:10–09:50 (40 min). Neither corrects the other, so the week's minutes are 145–155 against a goal of at least 150. Status cannot be determined.
- Week of Jan 26 was only evaluated through Jan 30. Jan 31–Feb 1 fall outside the requested period.

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

_timings (ms): {'plan_llm': 2775, 'execute': 7.58, 'narrate_llm': 26319, 'total': 29101}; LLM calls: 2, tokens in/out: 13196/3663, list-price cost $0.081; cached: False_