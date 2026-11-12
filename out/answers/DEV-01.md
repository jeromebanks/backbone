# DEV-01

> For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

# Rowan's therapy attendance, January 5–30, 2026 (HG-M042)

Rowan attended **12 therapy sessions on 11 distinct days**:
- **5 individual therapy sessions**
- **5 group therapy sessions**
- **2 family therapy sessions**

These counts are fully supported by the records. There are 11 days rather than 12 because Rowan had both a group session and an individual session on January 19. Patient-present time is 585–595 minutes (9.75–9.92 h). The range comes from one session whose start time the records disagree on.

## Sessions counted

| Date | Encounter | Type | Patient-present min | Source support |
|---|---|---|---|---|
| Jan 5 | HG-E101 | Individual | 50 | BH-D002 L6, L8; BH-D006 L10 |
| Jan 6 | HG-E102 | Group (partial) | 45 | BH-D005 L10; BH-D004 L12 (break 10:45–11:00) |
| Jan 9 | HG-E104 | Family | 45 | BH-D007 L6–7, L9; BH-D008 L6, L8 |
| Jan 12 | HG-E105 | Group | 75 | BH-D005 L11; BH-D009 L12 (break 10:40–10:55) |
| Jan 14 | HG-E107 | Individual | 45 | BH-D011 L6–7 |
| Jan 19 | HG-E110 | Group (partial) | 60 | BH-D102 L4, L9; BH-D103 L5, L7; BH-D101 L6 |
| Jan 19 | HG-E111 | Individual | 30 | BH-D105 L3, L6; BH-D103 L9 |
| Jan 21 | HG-E112 | Individual (video) | 45 | BH-D106 L5, L7; platform log L17–18 |
| Jan 22 | HG-E113 | Group (late arrival) | 45 | BH-D108 L9, L14; BH-D107 L7–8 |
| Jan 26 | HG-E115 | Individual | 40–50 (disputed) | BH-D110 L3, L7; BH-D111 L4, L7 |
| Jan 29 | HG-E118 | Group | 75 | BH-D108 L12, L20; BH-D107 L12 |
| Jan 30 | HG-E119 | Family (partial) | 30 | BH-D113 L5–7, L11 |

Minutes by type: individual 210–220, group 300, family 75.

## Records that could inflate the count if taken at face value

**More than one record for the same session (each counted once):**
- **HG-E104, Jan 9:** The primary clinician's note (BH-D007 L6) and the co-facilitator's note (BH-D008 L6–7) describe the same family session.
- **HG-E110, Jan 19:** BH-D104 is a resent copy of the original roster. It "contains no new clinician signature and records no additional visit" (BH-D104 L20), so it was not treated as separate evidence.
  - The original roster gave a departure time of 11:30 (BH-D102 L9). The correction document changes this to 11:15 (BH-D103 L7).
  - With the corrected time, the group no longer overlaps the individual session HG-E111 at 11:15–11:45 (BH-D105 L6). The room-transfer record shows Rowan leaving the group room at 11:15 and being received by the individual clinician at 11:15 (BH-D103 L9).
  - So these are two real sessions on one day.
- **HG-E112, Jan 21:** There were two video connections (VC-112A and VC-112B), but the second was a rejoin after a network disconnect. The note says the reconnection "continued the same clinical encounter" (BH-D106 L7, L17–19). It is one session; the 13:20–13:30 gap is excluded from minutes.
- **HG-E115, Jan 26:** Notes from two clinicians describe one session (BH-D110 L3, L6; BH-D111 L4).
- **Schedule and register listings** (BH-D006, BH-D015, BH-D108) and the combined group note covering two dates (BH-D107) support encounters that are already counted. They do not add sessions.

**Not attended (excluded):**
- **HG-E103, Jan 8, individual:** no-show (BH-D006 L12; BH-D015 L11).
- **HG-E108, Jan 15, group:** cancelled by the clinic for staff illness; "No group was held" (BH-D016 L9, L15).
- **HG-E116, Jan 27, group:** no-show; Rowan was "absent for the entire group" (BH-D108 L10, L16).
  - This is the main risk of an ineligible count. BH-D112 contains an unsigned draft note generated from a template, which says "Patient attended the full session" (BH-D112 L9, L11, L16). It also contains a posted charge for "1 group session" (BH-D112 L19–22).
  - Neither the draft nor the billing row counts as evidence of attendance, so the signed final register's no-show stands.
- **HG-E117, Jan 28, individual:** cancelled by the patient before the appointment (BH-D108 L11, L18).

**Not psychotherapy (excluded):**
- **Medication management:**
  - HG-E106, Jan 13: "No separate psychotherapy component" (BH-D010 L17).
  - HG-E120, Jan 30: "No separately documented psychotherapy" (BH-D114 L12).
- **Partner collateral, HG-E109, Jan 16:** Rowan was absent for the whole contact (BH-D012 L8, L17). The schedule lists it as "Completed" (BH-D006 L18), which could be misread as a session.
- **Care coordination, HG-E114, Jan 23:** professionals only, with no patient contact (BH-D109 L7, L13).
- **Outreach and administrative contacts:**
  - Jan 8 callback about scheduling; "No therapy intervention" (BH-D015 L15, L17).
  - Jan 15 portal notice and phone call confirming the cancellation (BH-D016 L11, L13, L15).
  - Jan 16 review of a PHQ-9 questionnaire submitted through the portal (BH-D013 L15).
  - Jan 27 outreach message (BH-D108 L16).

## What the record does not settle

- **HG-E115 minutes (40 vs 50):** The primary note gives 09:00–09:50, 50 minutes (BH-D110 L7). The second clinician's note gives 09:10–09:50, 40 minutes, and says Rowan "entered the treatment room at 09:10" (BH-D111 L7, L10). Neither note corrects the other, so the minutes are carried as a range. This affects minutes only, not the session count.
- **HG-E119 duration:** The note gives the therapist's session as 13:00–13:45, 45 minutes. Rowan was present only from 13:15 to 13:45 (BH-D113 L6–7). The count uses the 30 patient-present minutes, so it would be overstated if 45 minutes were used.
- **HG-E101 timing:** This session took place before the treatment plan was signed (2026-01-05T13:05), on the plan's first effective day. It is counted because the plan takes effect by date. A reviewer using a time-of-signature rule could treat it differently.
- **Uneven documentation:** Several sessions rest on one clinical note: HG-E107 (plus a schedule listing), HG-E112, and HG-E119.

## Not settled by the record

- HG-E115 (Jan 26) patient-present minutes are disputed: 50 min per BH-D110 vs 40 min per BH-D111. Neither note corrects the other, so minutes are carried as 40–50 and the total as 585–595.

## How this was computed

```
QueryPlan: For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.
  1. care(patients=['HG-M042'], 2026-01-05..2026-01-30, include_excluded, group_by=service_type)
  2. timeline(patients=['HG-M042'], 2026-01-05..2026-01-30, include_excluded, kinds=['encounters', 'documents', 'decisions'])
```

**care**

- sessions = count of encounters that count as therapy sessions = 12: HG-E101, HG-E102, HG-E104, HG-E105, HG-E107, HG-E110, HG-E111, HG-E112, HG-E113, HG-E115, HG-E118, HG-E119
- therapy days = distinct (patient, date) pairs among them = 11: 2026-01-05, 2026-01-06, 2026-01-09, 2026-01-12, 2026-01-14, 2026-01-19, 2026-01-21, 2026-01-22, 2026-01-26, 2026-01-29, 2026-01-30
- patient-present minutes = 50 (HG-E101) + 45 (HG-E102) + 45 (HG-E104) + 75 (HG-E105) + 45 (HG-E107) + 60 (HG-E110) + 30 (HG-E111) + 45 (HG-E112) + 45 (HG-E113) + [40–50] (HG-E115) + 75 (HG-E118) + 30 (HG-E119) = 585–595 min (9.75–9.92 h)

**timeline**

- patient-present minutes = 50 (HG-E101) + 45 (HG-E102) + 45 (HG-E104) + 75 (HG-E105) + 45 (HG-E107) + 60 (HG-E110) + 30 (HG-E111) + 45 (HG-E112) + 45 (HG-E113) + [40–50] (HG-E115) + 75 (HG-E118) + 30 (HG-E119) = 585–595

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
| BH-D006 | 12 | early_appointment_status_export.txt | schedule_listing | HG-E103   / Jan08 / Individual therapy     / 11:00–11:45    / No show |
| BH-D006 | 13 | early_appointment_status_export.txt | schedule_listing | HG-E104   / Jan09 / Family therapy         / 14:00–14:45    / Completed |
| BH-D006 | 14 | early_appointment_status_export.txt | schedule_listing | HG-E105   / Jan12 / Coping skills group    / 10:00–11:30    / Completed |
| BH-D006 | 15 | early_appointment_status_export.txt | schedule_listing | HG-E106   / Jan13 / Medication management  / 09:00–09:25    / Completed |
| BH-D006 | 16 | early_appointment_status_export.txt | schedule_listing | HG-E107   / Jan14 / Individual therapy     / 11:00–11:45    / Completed |
| BH-D006 | 17 | early_appointment_status_export.txt | schedule_listing | HG-E108   / Jan15 / Coping skills group    / 10:00–11:30    / Clinic cancelled |
| BH-D006 | 18 | early_appointment_status_export.txt | schedule_listing | HG-E109   / Jan16 / Family collateral      / 14:00–14:40    / Completed |
| BH-D006 | 20 | early_appointment_status_export.txt | schedule_listing | Appointment HG-E109 was retained as a partner collateral contact after Rowan could not attend. |
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
| BH-D010 | 6 | medication_review_jan13.txt | clinical_note | Encounter HG-E106 / Date 2026-01-13 |
| BH-D010 | 7 | medication_review_jan13.txt | clinical_note | Actual visit 09:00–09:25 local; completed, 25 minutes |
| BH-D010 | 11 | medication_review_jan13.txt | clinical_note | Rowan attended for medication management. |
| BH-D010 | 17 | medication_review_jan13.txt | clinical_note | Service documented: medication review and management only. No separate psychotherapy component was provided or documented. |
| BH-D011 | 6 | individual_therapy_jan14.txt | clinical_note | Encounter HG-E107 / Date 2026-01-14 |
| BH-D011 | 7 | individual_therapy_jan14.txt | clinical_note | Patient-present session 11:00–11:45 local; completed, 45 minutes |
| BH-D012 | 6 | partner_collateral_jan16.txt | clinical_note | Encounter HG-E109 / Date 2026-01-16 / 14:00–14:40 local |
| BH-D012 | 8 | partner_collateral_jan16.txt | clinical_note | Participant: Casey Mercer, partner. Rowan was absent for the entire contact. |
| BH-D012 | 17 | partner_collateral_jan16.txt | clinical_note | No patient-present psychotherapy occurred during this contact. |
| BH-D013 | 9 | symptom_measure_review_jan16.txt | clinical_note | Reviewed by Mara Voss, LCSW, 2026-01-16, 09:10 local |
| BH-D013 | 15 | symptom_measure_review_jan16.txt | clinical_note | This entry records review of the portal submission; no clinical appointment occurred at the time of review. |
| BH-D015 | 6 | missed_visit_outreach_jan08.txt | schedule_listing | Related appointment: HG-E103, 2026-01-08, 11:00–11:45 local |
| BH-D015 | 9 | missed_visit_outreach_jan08.txt | schedule_listing | 11:12: Reception notified the clinician that Rowan had not checked in. |
| BH-D015 | 11 | missed_visit_outreach_jan08.txt | schedule_listing | 11:45: Appointment marked no show. Rowan was not seen for the scheduled individual visit. |
| BH-D015 | 13 | missed_visit_outreach_jan08.txt | schedule_listing | The next scheduled appointment remained the family visit on January 9. |
| BH-D015 | 15 | missed_visit_outreach_jan08.txt | administrative_notice | 15:36: Rowan returned the call. |
| BH-D015 | 17 | missed_visit_outreach_jan08.txt | administrative_notice | The callback addressed scheduling and contact information. No therapy intervention was conducted. |
| BH-D016 | 9 | group_cancellation_notice_jan15.txt | administrative_notice | The coping skills group scheduled for January 15 from 10:00 to 11:30 is cancelled by the clinic because of staff illness. |
| BH-D016 | 11 | group_cancellation_notice_jan15.txt | administrative_notice | The notice states that the office initiated the cancellation and that the participant should not come to the group room this morning. |
| BH-D016 | 13 | group_cancellation_notice_jan15.txt | administrative_notice | Staff confirmed that the family-related appointment on January 16 remained on the schedule and that later appointments would appear on the next weekly list. |
| BH-D016 | 15 | group_cancellation_notice_jan15.txt | administrative_notice | The telephone contact was limited to confirming the cancellation and upcoming appointment information. |
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
| BH-D108 | 10 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 27 / HG-E116 / Skills group / 10:00–11:30 / — / — / No show; patient did not attend |
| BH-D108 | 11 | BH-D108_final_attendance_and_cancellation_register.txt | schedule_listing | January 28 / HG-E117 / Individual / 14:00–14:45 / — / — / Patient cancelled before appointment |
| BH-D108 | 12 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 29 / HG-E118 / Skills group / 10:00–11:30 / 10:00 / 11:30 / Attended |
| BH-D108 | 14 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 22, 12:09. |
| BH-D108 | 16 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | An outreach message inviting the patient to contact scheduling was left after the group; no clinical discussion occurred. |
| BH-D108 | 18 | BH-D108_final_attendance_and_cancellation_register.txt | schedule_listing | Appointment HG-E117 was cancelled before the scheduled start; no replacement appointment was booked within January 2026. |
| BH-D108 | 20 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 29, 12:15. |
| BH-D109 | 5 | BH-D109_care_coordination_2026-01-23.txt | clinical_note | January 23, 2026 / 09:00–09:20 |
| BH-D109 | 7 | BH-D109_care_coordination_2026-01-23.txt | clinical_note | Patient participation: None. No patient contact occurred. |
| BH-D109 | 13 | BH-D109_care_coordination_2026-01-23.txt | clinical_note | Rowan did not join by telephone or video, and no psychotherapy was delivered to the patient during the call. |
| BH-D110 | 3 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Individual psychotherapy / Encounter HG-E115 / Appointment HG-A115 |
| BH-D110 | 5 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | January 26, 2026 / In person |
| BH-D110 | 6 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Clinicians: Mira Patel, LCSW; Nora Ellis, LCSW |
| BH-D110 | 7 | BH-D110_individual_primary_record_2026-01-26.txt | clinical_note | Actual patient psychotherapy contact: 09:00–09:50, 50 minutes. |
| BH-D111 | 4 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Encounter HG-E115 / Appointment HG-A115 / Service date January 26, 2026 |
| BH-D111 | 7 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Actual patient psychotherapy contact: 09:10–09:50, 40 minutes. |
| BH-D111 | 10 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | Rowan entered the treatment room at 09:10, when we began the session. |
| BH-D111 | 14 | BH-D111_individual_second_record_2026-01-26.txt | clinical_note | The session concluded with Rowan at 09:50. |
| BH-D112 | 9 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Status: DRAFT — UNSIGNED — system populated from scheduled group template |
| BH-D112 | 10 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Scheduled service: Skills group, 10:00–11:30 |
| BH-D112 | 11 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Template attendance text: Patient attended the full session and participated in the skills discussion. |
| BH-D112 | 16 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | It was generated from the appointment template before the scheduled group. |
| BH-D112 | 19 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Charge ID: CH-116 / Encounter: HG-E116 |
| BH-D112 | 20 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Service date: January 27, 2026 / Posting date: January 27, 2026, 18:06 |
| BH-D112 | 21 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Description: Group psychotherapy |
| BH-D112 | 22 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Quantity charged: 1 group session |
| BH-D113 | 5 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | January 30, 2026 / In person / Clinician: Mira Patel, LCSW |
| BH-D113 | 6 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Therapist session interval: 13:00–13:45, 45 minutes. |
| BH-D113 | 7 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Partner only: 13:00–13:15. |
| BH-D113 | 11 | BH-D113_family_therapy_2026-01-30.txt | clinical_note | Rowan joined at 13:15 and participated through the end of the session. |
| BH-D114 | 5 | BH-D114_medication_management_2026-01-30.txt | clinical_note | January 30, 2026 / 15:00–15:20 / Completed, 20 minutes |
| BH-D114 | 12 | BH-D114_medication_management_2026-01-30.txt | clinical_note | No separately documented psychotherapy was provided. |

_timings (ms): {'plan_llm': 5430, 'execute': 9.63, 'narrate_llm': 58488, 'total': 63928}; LLM calls: 2, tokens in/out: 129912/6184, list-price cost $0.173; cached: False_