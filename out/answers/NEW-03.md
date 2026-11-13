# NEW-03

> How did the types and amount of therapy Rowan received change before versus after January 19, 2026?

# Rowan's therapy before vs. after January 19, 2026

Rowan received the same three therapy types in both periods: individual, group and family therapy. After January 19 there were more sessions and more patient-present minutes, both in total and per week. The "after" period is shorter (1.71 weeks, versus 2.0 weeks before), so the per-week figures are the fairer comparison.

| | Before (Jan 5–18, 2.0 wk) | After (Jan 19–30, 1.71 wk) |
|---|---|---|
| Sessions | 5 | 7 |
| Therapy days | 5 | 6 |
| Patient-present minutes | 260 (4.33 h) | 325–335 (5.42–5.58 h) |
| Minutes per week | 130.0 | 189.6–195.4 |
| Individual | 2 sessions / 95 min | 3 sessions / 115–125 min |
| Group | 2 sessions / 120 min | 3 sessions / 180 min |
| Family | 1 session / 45 min | 1 session / 30 min |

**Before (encounters HG-E101, E102, E104, E105, E107)**
- **Individual:** 50 min on Jan 5 (BH-D002 L8) and 45 min on Jan 14 (BH-D011 L7).
- **Group:** 45 min on Jan 6. Rowan arrived at 10:15 and left at 11:15, and the 10:45–11:00 break is not counted (BH-D005 L10; BH-D004 L12). The second group was 75 min on Jan 12 (BH-D005 L11; break per BH-D009 L12).
- **Family:** 45 min with partner Casey Mercer on Jan 9 (BH-D007 L7, L9; BH-D008 L8).

**After (encounters HG-E110, E111, E112, E113, E115, E118, E119)**
- **Group:**
  - 60 min on Jan 19. The departure time was corrected from 11:30 to 11:15 (BH-D103 L7).
  - 45 min on Jan 22, after a late arrival at 10:30 (BH-D108 L9).
  - 75 min on Jan 29 (BH-D108 L12; BH-D107 L8).
- **Individual:**
  - 30 min in person on Jan 19 (BH-D105 L6).
  - 45 min by video on Jan 21, with a 13:20–13:30 disconnection not counted (BH-D106 L7). This is the only video session in the window.
  - 40–50 min on Jan 26 (see below).
- **Family:** 30 min on Jan 30 (BH-D113 L7).

## What the record does not settle
- **Jan 26 individual session (HG-E115):** two clinical notes disagree. One gives 09:00–09:50, 50 min (BH-D110 L7). The other gives 09:10–09:50, 40 min, and says Rowan entered at 09:10 (BH-D111 L7, L10). Neither corrects the other, so the minutes are carried as the range 40–50. This is the only source of the ranges in the "after" figures.
- **Jan 30 family session (HG-E119):** the note gives a 45-minute therapist session interval (BH-D113 L6). However, only the partner was present from 13:00 to 13:15, and Rowan was present for 30 min (BH-D113 L7, L11). Only the 30 minutes are counted.
- **Modality:** not stated for some sessions (HG-E104, E107, E113, E118).
- **Interpretation:** the records show more sessions and more minutes per week after January 19. They do not explain why, and these figures say nothing about clinical outcomes.

## Excluded or merged records
- **Retransmitted copy:** BH-D104 is a copy of the Jan 19 roster. It still showed the old 11:30 departure and was not treated as independent evidence (BH-D104 L14, L20).
- **Scheduled but not attended:**
  - Before: a no-show for individual therapy on Jan 8 (HG-E103) and a clinic-cancelled group on Jan 15 (HG-E108).
  - After: a no-show for group therapy on Jan 27 (HG-E116) and a patient-cancelled individual session on Jan 28 (HG-E117).
- **Not psychotherapy:**
  - Medication management (HG-E106, HG-E120)
  - A family collateral contact (HG-E109)
  - Care coordination (HG-E114)
  - Outreach calls on Jan 8, Jan 15 and Jan 27
  - Administrative and other contacts on Jan 15–16

## Not settled by the record

- HG-E115 (Jan 26 individual) patient-present minutes disputed: 50 min per BH-D110 vs 40 min per BH-D111; carried as 40–50.

## How this was computed

```
QueryPlan: How did the types and amount of therapy Rowan received change before versus after January 19, 2026?
  1. compare(patients=['HG-M042'], 2026-01-05..2026-01-30, split=2026-01-19)
```

## Post-check

- numbers in the answer not found in computed results: none
- cited documents not in the corpus: none
- cited documents not in the computed results: none
- line references outside the evidence passages: none

## Evidence passages

| Doc | Lines | File | Record | Quote |
|---|---|---|---|---|
| BH-D002 | 6 | intake_and_individual_jan05.txt | clinical_note | Encounter HG-E101 / Service date 2026-01-05 |
| BH-D002 | 8 | intake_and_individual_jan05.txt | clinical_note | Patient-present individual therapy: 09:00–09:50 local; completed, 50 minutes. |
| BH-D002 | 13 | intake_and_individual_jan05.txt | clinical_note | Rowan arrived independently and participated throughout the appointment. |
| BH-D004 | 5 | group_facilitator_jan06.txt | clinical_note | Service date 2026-01-06 / Group scheduled 10:00–11:30 local |
| BH-D004 | 12 | group_facilitator_jan06.txt | clinical_note | The whole group took a break from 10:45 to 11:00. No therapy was conducted during that interval. |
| BH-D004 | 14 | group_facilitator_jan06.txt | clinical_note | Rowan was quiet initially and responded when invited to identify a situation involving avoidance. |
| BH-D005 | 10 | early_group_attendance_roster.txt | attendance_record | 2026-01-06 / HG-E102   / 10:00–11:30    / 10:15           / 11:15            / Attended part |
| BH-D005 | 11 | early_group_attendance_roster.txt | attendance_record | 2026-01-12 / HG-E105   / 10:00–11:30    / 10:00           / 11:30            / Attended full |
| BH-D005 | 13 | early_group_attendance_roster.txt | attendance_record | Rowan did not re-enter the group room after departing. |
| BH-D005 | 15 | early_group_attendance_roster.txt | attendance_record | Rowan checked in before the group began and remained until the group was released. |
| BH-D006 | 10 | early_appointment_status_export.txt | schedule_listing | HG-E101   / Jan05 / Individual therapy     / 09:00–09:50    / Completed |
| BH-D006 | 11 | early_appointment_status_export.txt | schedule_listing | HG-E102   / Jan06 / Coping skills group    / 10:00–11:30    / Attended part |
| BH-D006 | 13 | early_appointment_status_export.txt | schedule_listing | HG-E104   / Jan09 / Family therapy         / 14:00–14:45    / Completed |
| BH-D006 | 14 | early_appointment_status_export.txt | schedule_listing | HG-E105   / Jan12 / Coping skills group    / 10:00–11:30    / Completed |
| BH-D006 | 16 | early_appointment_status_export.txt | schedule_listing | HG-E107   / Jan14 / Individual therapy     / 11:00–11:45    / Completed |
| BH-D007 | 6 | family_primary_jan09.txt | clinical_note | Encounter HG-E104 / 2026-01-09, 14:00–14:45 local |
| BH-D007 | 7 | family_primary_jan09.txt | clinical_note | Present: Rowan and partner, Casey Mercer |
| BH-D007 | 9 | family_primary_jan09.txt | clinical_note | Patient-present family therapy duration: 45 minutes |
| BH-D007 | 16 | family_primary_jan09.txt | clinical_note | Rowan remained present and engaged throughout the visit. |
| BH-D008 | 6 | family_cofacilitator_jan09.txt | clinical_note | Encounter HG-E104 / Date 2026-01-09 / 14:00–14:45 local |
| BH-D008 | 7 | family_cofacilitator_jan09.txt | clinical_note | Author: Leena Park, LPC, cofacilitator with Mara Voss, LCSW |
| BH-D008 | 8 | family_cofacilitator_jan09.txt | clinical_note | Participants: Rowan Mercer and Casey Mercer; both present for the full 45 minutes |
| BH-D009 | 6 | group_facilitator_jan12.txt | clinical_note | Service date 2026-01-12 / Scheduled group 10:00–11:30 local |
| BH-D009 | 12 | group_facilitator_jan12.txt | clinical_note | Group break: 10:40–10:55; no therapeutic activity occurred during the break. |
| BH-D009 | 14 | group_facilitator_jan12.txt | clinical_note | Rowan contributed an example about leaving work messages unopened. |
| BH-D011 | 6 | individual_therapy_jan14.txt | clinical_note | Encounter HG-E107 / Date 2026-01-14 |
| BH-D011 | 7 | individual_therapy_jan14.txt | clinical_note | Patient-present session 11:00–11:45 local; completed, 45 minutes |
| BH-D015 | 13 | missed_visit_outreach_jan08.txt | schedule_listing | The next scheduled appointment remained the family visit on January 9. |
| BH-D101 | 3 | BH-D101_group_content_2026-01-19.txt | clinical_note | Skills group clinical record / Service date: January 19, 2026 |
| BH-D101 | 6 | BH-D101_group_content_2026-01-19.txt | clinical_note | Nontherapeutic break: 10:45–11:00. |
| BH-D101 | 10 | BH-D101_group_content_2026-01-19.txt | clinical_note | Patient-specific arrival and departure are maintained on the attendance roster. |
| BH-D102 | 4 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Service date: January 19, 2026 / Group encounter: HG-E110 |
| BH-D102 | 8 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Scheduled opening: 10:00 / Scheduled closing: 11:30 |
| BH-D102 | 9 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Patient arrival: 10:00 / Patient departure: 11:30 / Status: Attended |
| BH-D102 | 12 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Arrival and departure fields were entered at roster close. |
| BH-D103 | 5 | BH-D103_attendance_correction_2026-01-20.txt | attendance_correction | Applies to group encounter HG-E110, service date January 19, 2026 |
| BH-D103 | 7 | BH-D103_attendance_correction_2026-01-20.txt | attendance_correction | Correction: Patient departure for HG-E110 is 11:15, replacing the original roster value of 11:30. Patient arrival remains 10:00. |
| BH-D103 | 9 | BH-D103_attendance_correction_2026-01-20.txt | other | The room-transfer record shows Rowan leaving skills room B at 11:15 and being received by the individual clinician at 11:15. |
| BH-D103 | 11 | BH-D103_attendance_correction_2026-01-20.txt | other | It does not change the group service date, scheduled opening or closing, the break recorded in the group clinical note, or the separate individual appointment. |
| BH-D104 | 11 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Service date: January 19, 2026 / Group encounter: HG-E110 |
| BH-D104 | 13 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Scheduled opening: 10:00 / Scheduled closing: 11:30 |
| BH-D104 | 14 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Patient arrival: 10:00 / Patient departure: 11:30 / Status: Attended |
| BH-D104 | 20 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | The received copy contains no new clinician signature and records no additional visit. |
| BH-D105 | 3 | BH-D105_individual_2026-01-19.txt | clinical_note | Individual psychotherapy / Encounter HG-E111 |
| BH-D105 | 5 | BH-D105_individual_2026-01-19.txt | clinical_note | January 19, 2026 / In person |
| BH-D105 | 6 | BH-D105_individual_2026-01-19.txt | clinical_note | Patient contact: 11:15–11:45 / Completed: 30 minutes |
| BH-D105 | 11 | BH-D105_individual_2026-01-19.txt | clinical_note | Rowan participated throughout the individual contact and reported that the immediate intensity of anxiety eased enough to discuss a next step. |
| BH-D106 | 5 | BH-D106_telehealth_2026-01-21.txt | clinical_note | January 21, 2026 / Video / Clinician: Mira Patel, LCSW |
| BH-D106 | 7 | BH-D106_telehealth_2026-01-21.txt | clinical_note | Connection was lost from 13:20–13:30; there was no therapeutic contact during that interval. |
| BH-D106 | 17 | BH-D106_telehealth_2026-01-21.txt | platform_log | HG-A112 / VC-112A / January 21 13:00 / January 21 13:20 |
| BH-D106 | 18 | BH-D106_telehealth_2026-01-21.txt | platform_log | HG-A112 / VC-112B / January 21 13:30 / January 21 13:55 |
| BH-D106 | 19 | BH-D106_telehealth_2026-01-21.txt | platform_log | Second call reason: Rejoin original appointment after network disconnect. |
| BH-D106 | 20 | BH-D106_telehealth_2026-01-21.txt | platform_log | Exported January 21, 2026, 14:06; all times local. |
| BH-D107 | 7 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | January 22, 2026 / Encounter HG-E113 |
| BH-D107 | 8 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | Nontherapeutic break 10:45–11:00. |
| BH-D107 | 9 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | The patient contributed an example to the discussion after the break. |
| BH-D107 | 12 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | January 29, 2026 / Encounter HG-E118 |
| BH-D107 | 14 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | Rowan participated in the paired rehearsal and accepted feedback about keeping the request brief. |
| BH-D108 | 9 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 22 / HG-E113 / Skills group / 10:00–11:30 / 10:30 / 11:30 / Attended, late arrival |
| BH-D108 | 12 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 29 / HG-E118 / Skills group / 10:00–11:30 / 10:00 / 11:30 / Attended |
| BH-D108 | 14 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 22, 12:09. |
| BH-D108 | 20 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 29, 12:15. |
| BH-D110 | 3 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Individual psychotherapy / Encounter HG-E115 / Appointment HG-A115 |
| BH-D110 | 5 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | January 26, 2026 / In person |
| BH-D110 | 6 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Clinicians: Mira Patel, LCSW; Nora Ellis, LCSW |
| BH-D110 | 7 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Actual patient psychotherapy contact: 09:00–09:50, 50 minutes. |
| BH-D111 | 4 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Encounter HG-E115 / Appointment HG-A115 / Service date January 26, 2026 |
| BH-D111 | 7 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Actual patient psychotherapy contact: 09:10–09:50, 40 minutes. |
| BH-D111 | 10 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Rowan entered the treatment room at 09:10, when we began the session. |
| BH-D111 | 14 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | The session concluded with Rowan at 09:50. |
| BH-D113 | 5 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | January 30, 2026 / In person / Clinician: Mira Patel, LCSW |
| BH-D113 | 6 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Therapist session interval: 13:00–13:45, 45 minutes. |
| BH-D113 | 7 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Partner only: 13:00–13:15. |
| BH-D113 | 11 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Rowan joined at 13:15 and participated through the end of the session. |

_timings (ms): {'plan_llm': 2485, 'execute': 2.78, 'narrate_llm': 30945, 'total': 33433}; LLM calls: 2, tokens in/out: 20255/4217, list-price cost $0.094; cached: False_