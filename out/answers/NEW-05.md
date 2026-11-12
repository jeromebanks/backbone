# NEW-05

> How did Rowan's care change after their treatment plan was revised?

**The records don't show a revision to Rowan's (HG-M042) treatment plan in this period, so there is no before-and-after to compare.** Only one plan is on file, BH-D003, and it covers the whole window from 2026-01-05 to 2026-01-30. No change to that plan takes effect within those dates. Because there was no plan change to split the window on, the comparison produced no groups, totals or evidence lines. I can't describe a "before" or "after" pattern of care.

**What the computed output does contain**

The output only lists encounters in the window that were left out of the psychotherapy count. These exclusions are not a full record of Rowan's care. Any psychotherapy sessions Rowan attended would have been counted in the comparison groups, which are empty here because no comparison was made.

| Date | Encounter | Service type | Reason excluded |
|---|---|---|---|
| 2026-01-08 | HG-E103 | individual_therapy | not attended (no_show) |
| 2026-01-08 | U-2026-01-08-outreach_call-1 | outreach_call | not a psychotherapy service |
| 2026-01-13 | HG-E106 | medication_management | not a psychotherapy service |
| 2026-01-15 | HG-E108 | group_therapy | not attended (clinic_cancelled) |
| 2026-01-15 | U-2026-01-15-administrative-1 | administrative | not a psychotherapy service |
| 2026-01-15 | U-2026-01-15-outreach_call-1 | outreach_call | not a psychotherapy service |
| 2026-01-16 | HG-E109 | family_collateral | not a psychotherapy service |
| 2026-01-16 | U-2026-01-16-administrative-1 | administrative | not a psychotherapy service |
| 2026-01-16 | U-2026-01-16-other-1 | other | not a psychotherapy service |
| 2026-01-23 | HG-E114 | care_coordination | not a psychotherapy service |
| 2026-01-27 | HG-E116 | group_therapy | not attended (no_show) |
| 2026-01-27 | U-2026-01-27-outreach_call-1 | outreach_call | not a psychotherapy service |
| 2026-01-28 | HG-E117 | individual_therapy | not attended (patient_cancelled) |
| 2026-01-30 | HG-E120 | medication_management | not a psychotherapy service |

**What the record does not settle**
- Whether a plan revision happened outside 2026-01-05 to 2026-01-30. Only that window was checked. If you have a revision date in mind, re-running the comparison over a period that includes it would answer the question.
- Whether a revision was made but never filed as a separate plan document. Only BH-D003 is on file.
- How many psychotherapy sessions Rowan attended, and how often. The comparison returned no counts.
- No line-level evidence was returned, so the statements above are not tied to specific lines in BH-D003 or any other document.

## Not settled by the record

- No treatment-plan revision takes effect within 2026-01-05..2026-01-30; only BH-D003 (2026-01-05 to 2026-01-30) is on file, so the before/after comparison could not be made.
- Whether a revision occurred outside the queried window is unknown.
- Attended psychotherapy session counts for the window were not returned.

## How this was computed

```
QueryPlan: How did Rowan's care change after their treatment plan was revised?
  1. compare(patients=['HG-M042'], 2026-01-05..2026-01-30, split=plan_change)
```

## Post-check

- numbers in the answer not found in computed results: none
- cited documents not in the corpus: none
- line references outside the evidence passages: none


_timings (ms): {'plan_llm': 2622, 'execute': 1.08, 'narrate_llm': 14460, 'total': 17083}; LLM calls: 2, tokens in/out: 6714/1742, list-price cost $0.041; cached: False_