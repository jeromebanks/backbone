# NEW-01

> How many group therapy sessions were scheduled for Rowan in January 2026 that did not count as attended, and why did each one not count?

**Answer:** Two scheduled group therapy sessions in January 2026 did not count as attended for Rowan (HG-M042):

| Encounter | Date | Why it did not count | Sources |
|---|---|---|---|
| HG-E108 | 2026-01-15 | **The clinic cancelled it.** The clinic cancelled the coping skills group because of staff illness. "No group was held and no participants were seen for HG-E108," and nothing replaced it in that slot. | (BH-D016 L9, L15); schedule shows "Clinic cancelled" (BH-D006 L17, L20) |
| HG-E116 | 2026-01-27 | **Rowan didn't show up.** The final register reads "No show; patient did not attend." The final roster "confirms Rowan was absent for the entire group" and "No patient treatment contact occurred." | (BH-D108 L10, L16) |

**Records that seem to conflict for HG-E116**
- An unsigned draft note (BH-D112) says "Patient attended the full session." It is labelled "DRAFT — UNSIGNED — system populated from scheduled group template" and was "generated from the appointment template before the scheduled group" (BH-D112 L9, L11, L16). Template text doesn't count as proof of attendance, so it wasn't used.
- A billing row for the same encounter charges "1 group session" of "Group psychotherapy," posted January 27 (BH-D112 L19–L22). A charge doesn't count as proof of attendance either, so it wasn't used. Whether this charge should be reversed is outside these results.
- The signed final attendance register (BH-D108) decided the no-show.

**Context: sessions that did count.** Five group sessions counted as attended, totalling 300 minutes (5 hours) with Rowan present: HG-E102, HG-E105, HG-E110, HG-E113 and HG-E118. Two of these were partial attendances, and both still counted:
- **HG-E102 (Jan 6):** Rowan arrived at 10:15 and left at 11:15 for a ride, giving 45 minutes after the break (BH-D005 L10, L13).
- **HG-E110 (Jan 19):** a correction changed Rowan's departure from 11:30 to 11:15, giving 60 minutes (BH-D103 L7).

Also for HG-E110, a resent copy of the roster (BH-D104) was not treated as a separate session or as independent evidence. It "records no additional visit" (BH-D104 L20).

**Not settled by the record:** Nothing was in conflict, and all counts are firm (low = high). The results don't say whether either missed session was rescheduled. They also don't record a reason for the no-show.

## Not settled by the record

- Whether HG-E108 or HG-E116 was rescheduled is not documented in the results.
- No reason for the Jan 27 no-show is recorded.

## How this was computed

```
QueryPlan: How many group therapy sessions were scheduled for Rowan in January 2026 that did not count as attended, and why did each one not count?
  1. care(patients=['HG-M042'], 2026-01-01..2026-01-31, types=['group_therapy'], include_excluded, group_by=none)
```

**care**

- sessions = count of encounters that count as therapy sessions = 5: HG-E102, HG-E105, HG-E110, HG-E113, HG-E118
- therapy days = distinct (patient, date) pairs among them = 5: 2026-01-06, 2026-01-12, 2026-01-19, 2026-01-22, 2026-01-29
- patient-present minutes = 45 (HG-E102) + 75 (HG-E105) + 60 (HG-E110) + 45 (HG-E113) + 75 (HG-E118) = 300 min (5 h)

## Post-check

- numbers in the answer not found in computed results: none
- cited documents not in the corpus: none
- line references outside the evidence passages: none

## Evidence passages

| Doc | Lines | File | Record | Quote |
|---|---|---|---|---|
| BH-D004 | 5 | group_facilitator_jan06.txt | clinical_note | Service date 2026-01-06 / Group scheduled 10:00–11:30 local |
| BH-D004 | 12 | group_facilitator_jan06.txt | clinical_note | The whole group took a break from 10:45 to 11:00. No therapy was conducted during that interval. |
| BH-D004 | 14 | group_facilitator_jan06.txt | clinical_note | Rowan was quiet initially and responded when invited to identify a situation involving avoidance. |
| BH-D005 | 10 | early_group_attendance_roster.txt | attendance_record | 2026-01-06 / HG-E102   / 10:00–11:30    / 10:15           / 11:15            / Attended part |
| BH-D005 | 11 | early_group_attendance_roster.txt | attendance_record | 2026-01-12 / HG-E105   / 10:00–11:30    / 10:00           / 11:30            / Attended full |
| BH-D005 | 13 | early_group_attendance_roster.txt | attendance_record | Rowan did not re-enter the group room after departing. |
| BH-D005 | 15 | early_group_attendance_roster.txt | attendance_record | Rowan checked in before the group began and remained until the group was released. |
| BH-D006 | 11 | early_appointment_status_export.txt | schedule_listing | HG-E102   / Jan06 / Coping skills group    / 10:00–11:30    / Attended part |
| BH-D006 | 14 | early_appointment_status_export.txt | schedule_listing | HG-E105   / Jan12 / Coping skills group    / 10:00–11:30    / Completed |
| BH-D006 | 17 | early_appointment_status_export.txt | schedule_listing | HG-E108   / Jan15 / Coping skills group    / 10:00–11:30    / Clinic cancelled |
| BH-D006 | 20 | early_appointment_status_export.txt | schedule_listing | HG-E108 was removed from the active room schedule after staff illness was reported. |
| BH-D009 | 6 | group_facilitator_jan12.txt | clinical_note | Service date 2026-01-12 / Scheduled group 10:00–11:30 local |
| BH-D009 | 12 | group_facilitator_jan12.txt | clinical_note | Group break: 10:40–10:55; no therapeutic activity occurred during the break. |
| BH-D009 | 14 | group_facilitator_jan12.txt | clinical_note | Rowan contributed an example about leaving work messages unopened. |
| BH-D016 | 9 | group_cancellation_notice_jan15.txt | administrative_notice | The coping skills group scheduled for January 15 from 10:00 to 11:30 is cancelled by the clinic because of staff illness. |
| BH-D016 | 15 | group_cancellation_notice_jan15.txt | administrative_notice | No replacement group was conducted in the January 15 slot. |
| BH-D101 | 3 | BH-D101_group_content_2026-01-19.txt | clinical_note | Skills group clinical record / Service date: January 19, 2026 |
| BH-D101 | 6 | BH-D101_group_content_2026-01-19.txt | clinical_note | Nontherapeutic break: 10:45–11:00. |
| BH-D101 | 10 | BH-D101_group_content_2026-01-19.txt | clinical_note | Patient-specific arrival and departure are maintained on the attendance roster. |
| BH-D102 | 4 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Service date: January 19, 2026 / Group encounter: HG-E110 |
| BH-D102 | 8 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Scheduled opening: 10:00 / Scheduled closing: 11:30 |
| BH-D102 | 9 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Patient arrival: 10:00 / Patient departure: 11:30 / Status: Attended |
| BH-D102 | 12 | BH-D102_original_attendance_2026-01-19.txt | attendance_record | Arrival and departure fields were entered at roster close. |
| BH-D103 | 5 | BH-D103_attendance_correction_2026-01-20.txt | attendance_correction | Applies to group encounter HG-E110, service date January 19, 2026 |
| BH-D103 | 7 | BH-D103_attendance_correction_2026-01-20.txt | attendance_correction | Correction: Patient departure for HG-E110 is 11:15, replacing the original roster value of 11:30. Patient arrival remains 10:00. |
| BH-D103 | 9 | BH-D103_attendance_correction_2026-01-20.txt | attendance_correction | The group continued for other members until its scheduled close. |
| BH-D104 | 11 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Service date: January 19, 2026 / Group encounter: HG-E110 |
| BH-D104 | 13 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Scheduled opening: 10:00 / Scheduled closing: 11:30 |
| BH-D104 | 14 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | Patient arrival: 10:00 / Patient departure: 11:30 / Status: Attended |
| BH-D104 | 20 | BH-D104_resent_roster_received_2026-01-26.txt | retransmitted_copy | The received copy contains no new clinician signature and records no additional visit. |
| BH-D107 | 7 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | January 22, 2026 / Encounter HG-E113 |
| BH-D107 | 8 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | Nontherapeutic break 10:45–11:00. |
| BH-D107 | 9 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | The patient contributed an example to the discussion after the break. |
| BH-D107 | 12 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | January 29, 2026 / Encounter HG-E118 |
| BH-D107 | 14 | BH-D107_group_activity_records_2026-01-22_and_29.txt | clinical_note | Rowan participated in the paired rehearsal and accepted feedback about keeping the request brief. |
| BH-D108 | 9 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 22 / HG-E113 / Skills group / 10:00–11:30 / 10:30 / 11:30 / Attended, late arrival |
| BH-D108 | 10 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 27 / HG-E116 / Skills group / 10:00–11:30 / — / — / No show; patient did not attend |
| BH-D108 | 12 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | January 29 / HG-E118 / Skills group / 10:00–11:30 / 10:00 / 11:30 / Attended |
| BH-D108 | 14 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 22, 12:09. |
| BH-D108 | 16 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | No patient treatment contact occurred. |
| BH-D108 | 20 | BH-D108_final_attendance_and_cancellation_register.txt | attendance_record | Signed: Leah Chen, LCSW, January 29, 12:15. |
| BH-D112 | 9 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Status: DRAFT — UNSIGNED — system populated from scheduled group template |
| BH-D112 | 10 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Scheduled service: Skills group, 10:00–11:30 |
| BH-D112 | 11 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | Template attendance text: Patient attended the full session and participated in the skills discussion. |
| BH-D112 | 16 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | draft_template | It was generated from the appointment template before the scheduled group. |
| BH-D112 | 19 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Charge ID: CH-116 / Encounter: HG-E116 |
| BH-D112 | 20 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Service date: January 27, 2026 / Posting date: January 27, 2026, 18:06 |
| BH-D112 | 21 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Description: Group psychotherapy |
| BH-D112 | 22 | BH-D112_draft_note_and_charge_extract_2026-01-27.txt | billing | Quantity charged: 1 group session |

_timings (ms): {'plan_llm': 2844, 'execute': 6.97, 'narrate_llm': 18221, 'total': 21072}; LLM calls: 2, tokens in/out: 14437/2378, list-price cost $0.130; cached: False_