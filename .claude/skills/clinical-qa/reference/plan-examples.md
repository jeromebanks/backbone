# QueryPlan examples (question → plan)

All examples use patient `HG-M042` and the episode `2026-01-05..2026-01-30`. Replace these with values from
`python -m backbone directory`.

## How many sessions, by type, on how many days, and what could be double-counted?
```json
{"question": "Sessions by type and distinct days, with duplicate/ineligible records explained",
 "steps": [{"op": "care", "group_by": "service_type",
            "scope": {"patients": ["HG-M042"], "start": "2026-01-05", "end": "2026-01-30", "include_excluded": true}}]}
```

## Minutes and hours overall and per Monday–Sunday week
```json
{"question": "Therapy minutes and hours overall and by week",
 "steps": [{"op": "care", "group_by": "week",
            "scope": {"patients": ["HG-M042"], "start": "2026-01-05", "end": "2026-01-30", "include_excluded": true}}]}
```

## Did each week meet the treatment-plan goal? Two consecutive weeks below?
```json
{"question": "Weekly plan compliance",
 "steps": [{"op": "compliance", "consecutive_below": 2,
            "scope": {"patients": ["HG-M042"], "start": "2026-01-05", "end": "2026-01-30"}}]}
```

## Reconstruct specific dates (one step per date)
```json
{"question": "What happened on Jan 19 and Jan 21?",
 "steps": [
  {"op": "timeline", "kinds": ["encounters", "documents", "decisions"],
   "scope": {"patients": ["HG-M042"], "start": "2026-01-19", "end": "2026-01-19", "include_excluded": true}},
  {"op": "timeline", "kinds": ["encounters", "documents", "decisions"],
   "scope": {"patients": ["HG-M042"], "start": "2026-01-21", "end": "2026-01-21", "include_excluded": true}}]}
```

## Symptom course, distinct assessments, and why a contact happened
```json
{"question": "Symptom course and the reason for the Jan 19 extra contact",
 "steps": [
  {"op": "timeline", "kinds": ["assessments", "observations"],
   "scope": {"patients": ["HG-M042"], "start": "2026-01-05", "end": "2026-01-30"}},
  {"op": "timeline", "kinds": ["encounters", "documents", "decisions"],
   "scope": {"patients": ["HG-M042"], "start": "2026-01-19", "end": "2026-01-19", "include_excluded": true}}]}
```
Narrow the observations with `"observation_domains": ["sleep"]` (also: mood, anxiety, avoidance, functioning, safety,
engagement, overall_progress, other).

## Only group therapy; which ones didn't count?
```json
{"question": "Group sessions that did not count, and why",
 "steps": [{"op": "care", "group_by": "none",
            "scope": {"patients": ["HG-M042"], "start": "2026-01-01", "end": "2026-01-31",
                      "service_types": ["group_therapy"], "include_excluded": true}}]}
```

## Before vs after a date, or a treatment-plan change
```json
{"question": "Care before vs after Jan 19",
 "steps": [{"op": "compare", "split": "2026-01-19",
            "scope": {"patients": ["HG-M042"], "start": "2026-01-05", "end": "2026-01-30"}}]}
```
Use `"split": "plan_change"` to split at the first change of treatment-plan requirements. If there is no change, the
results include a note saying so; report that rather than inventing a split.

## Collection-wide: who had two consecutive weeks below their requirements?
```json
{"question": "Patients with two consecutive weeks below requirements",
 "steps": [{"op": "compliance", "consecutive_below": 2,
            "scope": {"patients": "all", "start": "2026-01-05", "end": "2026-01-30", "include_evidence": false}}]}
```
Report `definite` patients separately from `depends_on_unresolved` ones.

## Not expressible → say so
Vital signs, medication lists, diagnoses and billing totals have no operator. Answer that the computed engine cannot
answer it. Optionally offer quoted passages labelled **retrieved, not computed**.
