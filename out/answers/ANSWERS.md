# Answers: questions.json

## DEV-01

> For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

# Rowan (HG-M042): therapy sessions attended, January 5–30, 2026

Rowan attended **12 therapy sessions on 11 distinct days**:

- **5 individual therapy** sessions on 5 days
- **5 group therapy** sessions on 5 days
- **2 family therapy** sessions on 2 days

The sessions and the days are fully settled by the records. Only the minutes for one session are disputed. Total patient-present time is **585–595 min (9.75–9.92 h)**.

The total is 12 sessions but only 11 days because Jan 19 had a group session and a separate individual session back to back (BH-D103 L9).

## Sessions counted

| Date | Encounter | Type | Patient-present min | Source support |
|---|---|---|---|---|
| Jan 5 | HG-E101 | Individual | 50 | BH-D002 L6, L8, L13; BH-D006 L10 |
| Jan 6 | HG-E102 | Group (left early) | 45 | BH-D005 L10, L13; BH-D004 L12, L14; BH-D006 L11 |
| Jan 9 | HG-E104 | Family | 45 | BH-D007 L6–9, L16; BH-D008 L6, L8; BH-D006 L13 |
| Jan 12 | HG-E105 | Group | 75 | BH-D005 L11, L15; BH-D009 L12, L14; BH-D006 L14 |
| Jan 14 | HG-E107 | Individual | 45 | BH-D011 L6–7; BH-D006 L16 |
| Jan 19 | HG-E110 | Group (left early) | 60 | BH-D101 L6, L10; BH-D102 L9; BH-D103 L7 |
| Jan 19 | HG-E111 | Individual | 30 | BH-D105 L3, L5–6, L11; BH-D103 L9 |
| Jan 21 | HG-E112 | Individual (video) | 45 | BH-D106 L5, L7, L17–19 |
| Jan 22 | HG-E113 | Group (arrived late) | 45 | BH-D108 L9, L14; BH-D107 L7–9 |
| Jan 26 | HG-E115 | Individual | 40–50 (disputed) | BH-D110 L3, L7; BH-D111 L4, L7, L10 |
| Jan 29 | HG-E118 | Group | 75 | BH-D108 L12, L20; BH-D107 L12, L14 |
| Jan 30 | HG-E119 | Family (Rowan joined late) | 30 | BH-D113 L5–7, L11 |

Minutes by type: individual 210–220, group 300, family 75.

## Records that could lead to double counting (each kept as one session)

- **HG-E104 (Jan 9):** There are two signed notes, one from the primary clinician (BH-D007) and one from the cofacilitator (BH-D008 L7). They describe the same 14:00–14:45 session, so it counts once.
- **HG-E110 (Jan 19):** Three records cover this one group session:
  - the original roster, which says Rowan left at 11:30 (BH-D102 L9);
  - a correction changing the departure to 11:15 (BH-D103 L7);
  - a resent copy of the original roster, received Jan 26, that still says 11:30 and "records no additional visit" (BH-D104 L14, L20).
  
  The copy is not treated as separate evidence, and the corrected 11:15 departure is used. With 11:30, the group would overlap the individual session HG-E111 (11:15–11:45). With the correction, it doesn't.
- **HG-E112 (Jan 21):** The video platform shows two calls (VC-112A and VC-112B) because the connection dropped. The note says the reconnection "continued the same clinical encounter" (BH-D106 L7, L17–19). This is one session, and the 10 minutes offline are not counted.
- **HG-E115 (Jan 26):** Two clinicians each wrote a note for the same encounter (BH-D110, BH-D111). It counts once.
- **BH-D107 and BH-D108:** Each of these documents covers more than one encounter (Jan 22 and Jan 29). Each encounter is counted once.
- **BH-D006 and BH-D005:** These are a desk status export and an attendance roster. They support sessions already counted and add no extra sessions.

## Records excluded as ineligible

| Date | Record | Why it doesn't count |
|---|---|---|
| Jan 8 | HG-E103 individual | No-show (BH-D006 L12; BH-D015 L11) |
| Jan 8 | Outreach calls | Scheduling only; "No therapy intervention was conducted" (BH-D015 L13, L15, L17) |
| Jan 13 | HG-E106 | Medication management; no psychotherapy (BH-D010 L17) |
| Jan 15 | HG-E108 group | Cancelled by the clinic for staff illness; no group held (BH-D016 L9, L15) |
| Jan 15 | Portal notice and phone call | Administrative, about the cancellation (BH-D016 L11, L13, L15) |
| Jan 16 | HG-E109 "family collateral" | Partner only; "Rowan was absent for the entire contact" (BH-D012 L8, L17). The desk export lists it as "Completed" (BH-D006 L18). |
| Jan 16 | BH-D013 PHQ-9 review | Review of a portal submission; no appointment took place (BH-D013 L15) |
| Jan 16 | Mention of a family appointment | Schedule reference only (BH-D016 L13) |
| Jan 23 | HG-E114 | Care coordination between professionals only; no patient contact (BH-D109 L7, L13) |
| Jan 27 | HG-E116 group | No-show (BH-D108 L10, L16). See the note below. |
| Jan 27 | Outreach message | "No clinical discussion occurred" (BH-D108 L16) |
| Jan 28 | HG-E117 individual | Cancelled by the patient before the appointment (BH-D108 L11, L18) |
| Jan 30 | HG-E120 | Medication management; no psychotherapy (BH-D114 L12) |

**HG-E116 (Jan 27) is the main risk of a wrong count.** BH-D112 contains:
- an unsigned draft auto-filled from a template, saying the "Patient attended the full session" (L9, L11, L16);
- a posted charge for "1 group session" (L19–22).

Neither is attendance evidence. The draft was created before the group took place. The signed final roster records a no-show.

## Open issues

- **HG-E115 minutes are disputed.** BH-D110 records 09:00–09:50 (50 min, L7). BH-D111 records 09:10–09:50 (40 min, L7, L10). Neither note corrects the other, so the minutes are kept as a range of 40–50. That range is why the individual and overall minute totals are ranges. The session count is not affected.
- **HG-E119 duration differs.** The note gives the therapist session as 45 min (13:00–13:45). Rowan was present only for 13:15–13:45, so 30 min (BH-D113 L6–7) is used.
- **HG-E101 timing.** The session took place before the treatment plan was signed (13:05 on Jan 5). It is counted because the plan takes effect by date. If a different eligibility rule applies, this one should be checked.
- **HG-E104 includes the partner.** It is counted as family therapy with Rowan present for the full session (BH-D008 L8).

This summary covers attendance and eligibility only. It does not judge clinical progress.

_Details, plan, calculations and evidence: [DEV-01.md](DEV-01.md)_

## DEV-02

> How many therapy minutes and hours did Rowan actually receive during the review period, overall and for each Monday–Sunday week? Show calculations or supporting detail, and report any conclusion the available documents do not settle.

# Rowan's therapy minutes and hours, 5–30 January 2026

**Answer:** Rowan received **12 therapy sessions on 11 days**, totalling **585–595 patient-present minutes (9.75–9.92 hours)**. The total is a range rather than one number because of a single dispute: the 26 January individual session (HG-E115) is recorded in two notes as either 40 or 50 minutes. Every other session's minutes are settled by the records.

By service type: individual therapy was 5 sessions and 210–220 min, group therapy 5 sessions and 300 min, and family therapy 2 sessions and 75 min.

## By Monday–Sunday week

| Week starting | Sessions (days) | Calculation | Minutes | Hours |
|---|---|---|---|---|
| 2026-01-05 | 3 (3) | 50 (HG-E101) + 45 (HG-E102) + 45 (HG-E104) | 140 | 2.33 |
| 2026-01-12 | 2 (2) | 75 (HG-E105) + 45 (HG-E107) | 120 | 2 |
| 2026-01-19 | 4 (3) | 60 (HG-E110) + 30 (HG-E111) + 45 (HG-E112) + 45 (HG-E113) | 180 | 3 |
| 2026-01-26 | 3 (3) | [40–50] (HG-E115) + 75 (HG-E118) + 30 (HG-E119) | 145–155 | 2.42–2.58 |
| **Total** | **12 (11)** | | **585–595** | **9.75–9.92** |

The review period ends on Friday 30 January, so the last week covers Monday to Friday only.

## Where each session's minutes come from
- **HG-E101, 5 Jan, individual:** 09:00–09:50, so 50 min (BH-D002 L8).
  - It was counted even though it started before the plan was signed (13:05 that day). The plan takes effect by date, and 5 January is its first effective day.
- **HG-E102, 6 Jan, group:** Rowan was present 10:15–11:15 (BH-D005 L10), minus a 10:45–11:00 group break (BH-D004 L12), so 45 min.
- **HG-E104, 9 Jan, family:** 14:00–14:45, so 45 min. Both clinicians' notes describe the same session (BH-D007 L6, L9; BH-D008 L8), so it counts once.
- **HG-E105, 12 Jan, group:** 10:00–11:30 (BH-D005 L11), minus a 10:40–10:55 break (BH-D009 L12), so 75 min.
- **HG-E107, 14 Jan, individual:** 11:00–11:45, so 45 min (BH-D011 L7).
- **HG-E110, 19 Jan, group:** 10:00–11:15, minus a 10:45–11:00 break (BH-D101 L6), so 60 min.
  - The original roster said Rowan left at 11:30 (BH-D102 L9). A formal correction changed this to 11:15 (BH-D103 L7).
  - The 11:15 time also fits the room-transfer record (BH-D103 L9) and the individual session that started at 11:15.
- **HG-E111, 19 Jan, individual:** 11:15–11:45, so 30 min (BH-D105 L6).
- **HG-E112, 21 Jan, video individual:** 13:00–13:20 plus 13:30–13:55, so 45 min. The 10-minute disconnection is excluded (BH-D106 L7, L17–18).
- **HG-E113, 22 Jan, group:** Rowan arrived late at 10:30 and stayed to 11:30 (BH-D108 L9, L14), minus the 10:45–11:00 break (BH-D107 L8), so 45 min.
- **HG-E118, 29 Jan, group:** 10:00–11:30 (BH-D108 L12, L20), minus the 10:45–11:00 break (BH-D107 L8), so 75 min.
- **HG-E119, 30 Jan, family:** 30 min counted. The therapist's session ran 13:00–13:45 (45 min), but the partner was seen alone for the first 15 minutes. Rowan was present only from 13:15 to 13:45 (BH-D113 L6–7, L11).

## What the record does not settle
- **HG-E115 (26 Jan) is either 40 or 50 minutes.** Two signed clinical notes for the same appointment disagree, and neither corrects the other:
  - BH-D110 L7 records 09:00–09:50, which is 50 min.
  - BH-D111 L7 and L10 record 09:10–09:50, which is 40 min, and says "Rowan entered the treatment room at 09:10."
  - Because of this, the total for the week of 26 January and the overall total are ranges. Resolving it would require the clinicians to confirm which note is accurate or to file a formal correction.

## Records excluded or set aside
**Scheduled but not attended:**
- HG-E103, 8 Jan, individual: no-show (BH-D006 L12; BH-D015 L11).
- HG-E108, 15 Jan, group: cancelled by the clinic because of staff illness (BH-D016 L9, L15).
- HG-E116, 27 Jan, group: no-show (BH-D108 L10, L16). Two documents suggest Rowan attended, but neither counts as attendance evidence:
  - An unsigned draft note generated from a template before the group took place (BH-D112 L9, L11, L16).
  - A billing charge for one group session (BH-D112 L19–22).
- HG-E117, 28 Jan, individual: cancelled by Rowan before the appointment (BH-D108 L11, L18).

**Contacts that were not psychotherapy:**
- Medication management on 13 Jan (HG-E106; BH-D010 L17) and 30 Jan (HG-E120; BH-D114 L12).
- Partner-only collateral session on 16 Jan (HG-E109). Rowan was absent (BH-D012 L8, L17).
- Care coordination between professionals on 23 Jan (HG-E114). There was no contact with Rowan (BH-D109 L7, L13).
- Outreach and scheduling calls on 8 Jan (BH-D015 L17), 15 Jan (BH-D016 L15) and 27 Jan (BH-D108 L16).
- Portal notices and a symptom-measure review (BH-D016 L11; BH-D013 L15).

**Copies that are not independent evidence:**
- BH-D104 is a re-sent copy of the 19 January roster. It still shows the uncorrected 11:30 departure and "records no additional visit" (BH-D104 L14, L20), so it was not counted separately.

These figures count only the minutes Rowan was actually present. They show how much therapy was delivered, not whether Rowan's symptoms or functioning changed.

_Details, plan, calculations and evidence: [DEV-02.md](DEV-02.md)_

## DEV-03

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

_Details, plan, calculations and evidence: [DEV-03.md](DEV-03.md)_

## DEV-04

> Reconstruct the care on January 19 and January 21. How many therapy contacts and patient therapy minutes occurred on each date, and how do the attendance records, clinical notes, later documents, and telehealth records affect your answer?

**Answer:** On January 19, 2026 there were **2 therapy contacts** totalling **90 patient-present minutes (1.5 h)**: a 60-minute group and a 30-minute individual session. On January 21, 2026 there was **1 therapy contact** of **45 minutes (0.75 h)**: an individual video session. These figures are firm (low = high) on both dates.

| Date | Encounter | Type / modality | Minutes | Basis |
|---|---|---|---|---|
| Jan 19 | HG-E110 | Group therapy, in person (left early) | 60 | 10:00–11:15 minus break 10:45–11:00 (BH-D101 L6; BH-D102 L9; BH-D103 L7) |
| Jan 19 | HG-E111 | Individual therapy, in person | 30 | Contact 11:15–11:45 (BH-D105 L6) |
| **Jan 19 total** | 2 contacts | | **90** | |
| Jan 21 | HG-E112 | Individual therapy, video | 45 | 13:00–13:20 + 13:30–13:55 (BH-D106 L7) |
| **Jan 21 total** | 1 contact | | **45** | |

**How each type of record affects the answer**

- **Attendance records (Jan 19):** The original signed roster gives arrival 10:00 and departure 11:30 (BH-D102 L9). On its own that would credit the full group time.
- **Later correction (Jan 19):** A correction signed January 20 changes only the departure time, from 11:30 to 11:15. Arrival stays at 10:00 (BH-D103 L5, L7). It cites a room-transfer record: Rowan left skills room B at 11:15 and the individual clinician received them at 11:15 (BH-D103 L9). The note also says the correction does not change the break or the separate individual appointment (BH-D103 L11).
  - The software used the corrected time. The original 11:30 departure would have overlapped the 11:15–11:45 individual session; the corrected time does not.
  - The correction names no encounter ID for the individual session. It was linked to HG-E111 by date and service type only.
- **Group clinical note (Jan 19):** This supplies the scheduled time (10:00–11:30) and the non-therapy break (10:45–11:00), which is subtracted. It says the patient's own arrival and departure are kept on the roster (BH-D101 L6, L10).
- **Individual note (Jan 19):** This documents the added in-person visit, 11:15–11:45, "Completed: 30 minutes" (BH-D105 L3, L5–6). It is a separate contact, not part of the group time.
- **Later re-sent copy (excluded):** A roster copy received January 26 still shows departure 11:30 (BH-D104 L14). It was not counted as independent evidence because it is a retransmitted copy. It "contains no new clinician signature and records no additional visit" (BH-D104 L20). It adds no contact and does not override the correction.
- **Telehealth records (Jan 21):** The video note documents contact from 13:00–13:20 and 13:30–13:55. The connection dropped from 13:20–13:30 with "no therapeutic contact," for a stated total of 45 minutes (BH-D106 L5, L7). The platform export shows two calls, VC-112A and VC-112B, under the same appointment HG-A112. The second call's stated reason is "Rejoin original appointment after network disconnect" (BH-D106 L17–19). The note says the reconnection "continued the same clinical encounter" (BH-D106 L7). So the two calls count as **one contact**, not two, and the 10-minute gap is not counted.

**Not settled by the record / interpretation**
- No conflicts or uncertain encounters were flagged on either date.
- The 60 minutes for HG-E110 depends on accepting the January 20 correction. The original roster on its own would support a longer stay.
- The notes describe how the patient took part (e.g., BH-D101 L10; BH-D105 L11). I make no claims about clinical progress beyond what those notes say.

_Details, plan, calculations and evidence: [DEV-04.md](DEV-04.md)_

## DEV-05

> Summarize the documented symptom course during the episode and the reason for the additional individual contact on January 19. Which symptom assessments are distinct, and what conclusions about progress can and cannot be supported?

# Rowan (HG-M042): symptom course, January 5–30, 2026

## Direct answer
- **Symptom scores:** Three distinct PHQ-9 administrations are on record. The totals were **18** on Jan 5, **14** on Jan 16 and **10** on Jan 30. Each later score is lower than the one before.
- **What the clinician concluded:** On Jan 16 the clinician noted "some improvement in depressive symptoms." On Jan 30 the clinician judged "partial improvement." Both times the clinician also recorded that avoidance and functional impact around returning to work were still present.
- **Why there was an extra visit on January 19:** Rowan became anxious during the skills group and needed individual grounding and a review of coping strategies (BH-D105 L9). The group facilitator arranged a same-day individual visit (BH-D101 L10). That visit (encounter HG-E111) ran 11:15–11:45, 30 min (BH-D105 L6).

## Distinct symptom assessments

| Date | Instrument | Total | Recorded in | Notes |
|---|---|---|---|---|
| 2026-01-05 | PHQ-9 | 18 | BH-D002 L15 | Intake; no form ID; no item scores recorded |
| 2026-01-16 | PHQ-9 | 14 | BH-D013 L7, L11 | Form HG-Q116; completed via portal |
| 2026-01-30 | PHQ-9 | 10 | BH-D115 L6 | Item 9: 0 |

**Excluded as a copy:** BH-D014, an imported measure summary received Jan 26, repeats the same Jan 16 PHQ-9 (14, form HG-Q116) (BH-D014 L13). It is not counted as a separate assessment. No anxiety measure or other instrument appears in the results.

## Documented course (facts from the record)
- **Intake (Jan 5):**
  - Rowan reported several weeks of low mood, reduced interest, fragmented sleep, trouble starting tasks, and avoidance of email and of conversations about a return date (BH-D002 L11).
  - The clinician's impression was depressive symptoms with anxiety and behavioral avoidance (BH-D002 L15; BH-D003 L10).
- **Jan 13–14:**
  - Mood was "somewhat less heavy on days with a planned activity," but sleep interruption continued (BH-D010 L11). The clinician assessed ongoing depressive and anxiety symptoms (BH-D010 L15).
  - Rowan opened a work message and took two short walks but had not replied to the message (BH-D011 L11).
  - Affect was "more varied than at intake" (BH-D011 L15).
- **Jan 16:**
  - The PHQ-9 of 14 was reviewed. The clinician recorded that persistent avoidance, difficulty starting work communication and sleep disruption "remain clinically relevant" (BH-D013 L13).
  - The partner contact that day was collateral only; Rowan told the office they could not take part (BH-D012 L11). Casey reported short walks and fewer unplanned reminders, but said mornings are still difficult (BH-D012 L13).
- **Jan 19:**
  - In group, Rowan became visibly tense when talk turned to returning to the workplace (BH-D101 L10) and asked for more help (BH-D102 L14).
  - In the added individual visit, Rowan named muscle tension, rapid breathing and an urge to leave as early signs of activation. Rowan said the anxiety "eased enough to discuss a next step" (BH-D105 L9, L11).
  - Rowan denied suicidal thoughts and the clinician found no acute safety concern (BH-D105 L13).
- **Jan 21–26:**
  - Rowan drafted a message to work but did not send it, and reported one better night of sleep followed by prolonged wakefulness (BH-D106 L9, L11).
  - By Jan 26, Rowan had sent a short message to the supervisor but kept putting off scheduling the follow-up conversation (BH-D110 L9).
  - The clinician recorded "ongoing anxiety, low mood, and functional difficulty around work demands" (BH-D111 L14).
- **Jan 30:**
  - Rowan reported fewer days of pervasive low mood than at intake, and that sleep was still a problem (BH-D115 L8; BH-D114 L8).
  - Anxiety was still noticeable when anticipating contact with work (BH-D114 L8).
  - The clinician judged partial improvement, recommended continued treatment (BH-D115 L10, L12), and found no new acute safety issue (BH-D114 L10).
- **Missed or partial attendance:**
  - Jan 8: no-show for an individual visit (BH-D015 L9).
  - Jan 22: arrived late to group and stayed until it closed (BH-D108 L14).
  - Jan 27: missed the whole group (BH-D108 L16).
  - Jan 28: cancelled an individual visit (BH-D108 L18).

## January 19 records
- **Group (HG-E110):**
  - The original roster said Rowan left at 11:30 (BH-D102 L9). A signed correction changed this to 11:15 (BH-D103 L7). It is supported by a room-transfer record showing Rowan was received by the individual clinician at 11:15 (BH-D103 L9).
  - With the 10:45–11:00 break removed (BH-D101 L6), group time counts as 60 min.
- **Individual visit (HG-E111):** 30 min (BH-D105 L6).
- **Day total:** 90 patient-present minutes over 2 sessions.
- **Excluded record:** BH-D104 is a resent copy of the roster with the old 11:30 departure time (BH-D104 L14). It is not independent evidence and records no additional visit (BH-D104 L20).

## What the record supports
- The PHQ-9 totals went down across the three distinct administrations (18 → 14 → 10).
- The clinician documented "some" improvement on Jan 16 (BH-D013 L13) and "partial" improvement on Jan 30 (BH-D115 L10). Rowan's own reports describe mood as less persistently low (BH-D114 L8; BH-D115 L8).
- Rowan took small behavioral steps: opening a work message (BH-D011 L11), then sending one to the supervisor (BH-D110 L9).

## What the record does not support
- **A clinical response or remission label.** The record never states one, and the clinician's own wording is limited to "some" and "partial" improvement.
- **That treatment or medication caused the change.** No document makes that link.
- **Improvement in anxiety, sleep or work functioning.** Anxiety is still documented on Jan 30 (BH-D114 L8; BH-D113 L13). Sleep is still "variable" (BH-D114 L8), and avoidance and delayed follow-through persist (BH-D115 L10). There was no anxiety instrument to measure change.
- **Item-level change in symptoms.** The only item score is item 9 = 0 on Jan 30.
- **That Rowan completed their own work task on Jan 19.** The clinician cautioned that taking part in the group exercise should not be read as completing their own work task (BH-D101 L12).

_Details, plan, calculations and evidence: [DEV-05.md](DEV-05.md)_
