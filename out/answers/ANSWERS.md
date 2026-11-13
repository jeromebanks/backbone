# Answers: questions.json

## DEV-01

> For January 5–30, 2026, how many therapy sessions did Rowan attend, by service type and in total, and on how many distinct days? Provide a reviewable abstraction with source support and explain records that could lead to duplicate or ineligible counts.

# Rowan (HG-M042): therapy sessions attended, January 5–30, 2026

## Answer

Rowan attended **12 therapy sessions on 11 distinct days**. Both counts are firm. Two sessions were on the same day: group and individual therapy on 2026-01-19.

| Service type | Sessions | Days | Patient-present minutes |
|---|---|---|---|
| Individual therapy | 5 | 5 | 210–220 (range) |
| Group therapy | 5 | 5 | 300 |
| Family therapy | 2 | 2 | 75 |
| **Total** | **12** | **11** | **585–595 (9.75–9.92 h)** |

## Session-by-session abstraction

| Date | Encounter | Type | Status | Minutes | Source |
|---|---|---|---|---|---|
| 2026-01-05 | HG-E101 | Individual | Attended in full | 50 | BH-D002 L6, L8, L13; BH-D006 L10 |
| 2026-01-06 | HG-E102 | Group | Partial: 10:15–11:15, minus the 10:45–11:00 break | 45 | BH-D005 L10, L13; BH-D004 L12 |
| 2026-01-09 | HG-E104 | Family | Attended in full | 45 | BH-D007 L6–7, L9; BH-D008 L6, L8 |
| 2026-01-12 | HG-E105 | Group | Attended in full, minus the 10:40–10:55 break | 75 | BH-D005 L11, L15; BH-D009 L12 |
| 2026-01-14 | HG-E107 | Individual | Attended in full | 45 | BH-D011 L6–7 |
| 2026-01-19 | HG-E110 | Group | Partial: 10:00–11:15 (corrected), minus break | 60 | BH-D102 L9; BH-D103 L7; BH-D101 L6 |
| 2026-01-19 | HG-E111 | Individual | 11:15–11:45 | 30 | BH-D105 L3, L5–6 |
| 2026-01-21 | HG-E112 | Individual (video) | 13:00–13:20 + 13:30–13:55 | 45 | BH-D106 L7, L17–18 |
| 2026-01-22 | HG-E113 | Group | Late arrival at 10:30, minus break | 45 | BH-D108 L9, L14; BH-D107 L7–9 |
| 2026-01-26 | HG-E115 | Individual | Attended; length disputed | 40–50 | BH-D110 L7; BH-D111 L7, L10 |
| 2026-01-29 | HG-E118 | Group | Attended in full, minus break | 75 | BH-D108 L12, L20; BH-D107 L8, L12 |
| 2026-01-30 | HG-E119 | Family | Partial: Rowan present 13:15–13:45 | 30 | BH-D113 L6–7, L11 |

## Records that could cause duplicate counts (each counted once)

- **HG-E104 (Jan 9):** two notes for one family session, one from the primary clinician (BH-D007 L6) and one from the co-facilitator (BH-D008 L6–7). Count it once.
- **HG-E110 (Jan 19):**
  - BH-D104 is a resent copy of the attendance roster. It says it "records no additional visit" (BH-D104 L11, L14, L20), so it is not separate evidence.
  - The original roster's departure time of 11:30 (BH-D102 L9) was corrected to 11:15 (BH-D103 L7). With the original time, the group would overlap the 11:15 individual session (HG-E111).
- **HG-E112 (Jan 21):** the video platform logged two calls, VC-112A and VC-112B. The second was a rejoin of the same appointment after a network drop, so it is one session (BH-D106 L7, L17–19).
- **HG-E115 (Jan 26):** two clinical notes describe the same encounter and appointment (BH-D110 L3, L6; BH-D111 L4). It is one session, but the two notes give different times (see below).
- **Schedule export BH-D006:** it lists encounters already documented in clinical notes (e.g., BH-D006 L10–11, L13–14, L16). It confirms those sessions and adds none.
- **Records without an encounter ID:**
  - BH-D015 was linked to HG-E104 by date and service type.
  - BH-D103 was linked to HG-E111 the same way.

## Records excluded as ineligible

- **Scheduled but not attended:**
  - HG-E103, Jan 8, individual: no-show (BH-D006 L12; BH-D015 L11).
  - HG-E108, Jan 15, group: cancelled by the clinic (BH-D016 L9, L15).
  - HG-E117, Jan 28, individual: cancelled by the patient (BH-D108 L11, L18).
  - HG-E116, Jan 27, group: no-show (BH-D108 L10, L16). Two records in BH-D112 could make this look attended, and neither is attendance evidence:
    - An unsigned draft note generated from a template, saying the patient "attended the full session" (BH-D112 L9, L11, L16).
    - A billing charge for "1 group session" (BH-D112 L19, L21–22).
- **Not psychotherapy:**
  - Medication management on Jan 13 (HG-E106) and Jan 30 (HG-E120); both notes say no psychotherapy was provided (BH-D010 L17; BH-D114 L12).
  - HG-E109, Jan 16: a meeting with Rowan's partner only. Rowan was absent and no patient-present psychotherapy took place (BH-D012 L8, L17).
  - HG-E114, Jan 23: care coordination between professionals; no patient contact (BH-D109 L7, L13).
  - Jan 16 portal review of a symptom questionnaire (BH-D013 L15).
  - Outreach and scheduling calls or messages on Jan 8 (BH-D015 L13, L15, L17), Jan 15 (BH-D016 L11, L13, L15) and Jan 27 (BH-D108 L16).

## What the record does not settle

- **HG-E115 length:**
  - BH-D110 gives 09:00–09:50, or 50 minutes (BH-D110 L7).
  - BH-D111 gives 09:10–09:50, or 40 minutes, and says Rowan entered the room at 09:10 (BH-D111 L7, L10).
  - Neither note corrects the other, so the minutes stay as a range. The session counts either way.
- **HG-E119 length:** the note gives a 45-minute therapist session (BH-D113 L6). Rowan was present only for 30 of those minutes, because the first part was partner only (BH-D113 L7). The 30 minutes is used.
- **HG-E101 timing:** this session took place on the treatment plan's first effective day but before the plan was signed (13:05). It is counted because plan effectivity is applied by date. A reviewer using a time-of-signature rule could treat it differently.
- **Format:** the records do not say whether these sessions were in person, video or phone: HG-E104, HG-E107, HG-E113 and HG-E118. This does not change the counts.

_Details, plan, calculations and evidence: [DEV-01.md](DEV-01.md)_

## DEV-02

> How many therapy minutes and hours did Rowan actually receive during the review period, overall and for each Monday–Sunday week? Show calculations or supporting detail, and report any conclusion the available documents do not settle.

# Rowan's therapy minutes and hours, 2026-01-05 to 2026-01-30

**Rowan received 585–595 minutes (9.75–9.92 hours) of therapy with Rowan present.** This covers 12 therapy sessions on 11 days. The total is a range rather than one figure because of one encounter: the two notes for HG-E115 on 2026-01-26 record different contact times. The records settle the minutes for every other session.

## By Monday–Sunday week

| Week starting | Sessions | Therapy days | Calculation | Minutes | Hours |
|---|---|---|---|---|---|
| 2026-01-05 | 3 | 3 | 50 (HG-E101) + 45 (HG-E102) + 45 (HG-E104) | 140 | 2.33 |
| 2026-01-12 | 2 | 2 | 75 (HG-E105) + 45 (HG-E107) | 120 | 2 |
| 2026-01-19 | 4 | 3 | 60 (HG-E110) + 30 (HG-E111) + 45 (HG-E112) + 45 (HG-E113) | 180 | 3 |
| 2026-01-26 | 3 | 3 | [40–50] (HG-E115) + 75 (HG-E118) + 30 (HG-E119) | 145–155 | 2.42–2.58 |
| **Total** | **12** | **11** | | **585–595** | **9.75–9.92** |

The review period ends 2026-01-30, so the last week is counted only through that date. The rest of that week is not covered.

**By service type:**
- **Group:** 5 sessions, 300 minutes.
- **Individual:** 5 sessions, 210–220 minutes.
- **Family:** 2 sessions, 75 minutes.

## How each session's minutes were worked out

- **HG-E101 (2026-01-05, individual):** 09:00–09:50 = 50 min (BH-D002 L8). The session began before the treatment plan was signed that day. It was still counted because the plan takes effect by date.
- **HG-E102 (2026-01-06, group):** Rowan arrived at 10:15 and left at 11:15 (BH-D005 L10). Subtracting the group break from 10:45 to 11:00 (BH-D004 L12) gives 45 min.
- **HG-E104 (2026-01-09, family):** 14:00–14:45 = 45 min, with Rowan present (BH-D007 L9; BH-D008 L8).
- **HG-E105 (2026-01-12, group):** Rowan attended 10:00–11:30 (BH-D005 L11). Subtracting the break from 10:40 to 10:55 (BH-D009 L12) gives 75 min.
- **HG-E107 (2026-01-14, individual):** 11:00–11:45 = 45 min (BH-D011 L7).
- **HG-E110 (2026-01-19, group):** Rowan attended 10:00–11:15. Subtracting the 10:45–11:00 break gives 60 min (BH-D103 L7; BH-D101 L6).
  - The original roster had Rowan leaving at 11:30 (BH-D102 L9). The correction in BH-D103 changed that to 11:15 and changed nothing else.
  - The uncorrected time would overlap the individual session that began at 11:15. A room-transfer record shows Rowan going to the individual clinician at 11:15 (BH-D103 L9).
- **HG-E111 (2026-01-19, individual):** 11:15–11:45 = 30 min (BH-D105 L6).
- **HG-E112 (2026-01-21, video):** 13:00–13:20 plus 13:30–13:55 = 45 min. The 13:20–13:30 connection loss is not counted, because no therapy took place during it (BH-D106 L7, L17–18).
- **HG-E113 (2026-01-22, group):** Rowan arrived late at 10:30 and stayed until 11:30 (BH-D108 L9, L14). Subtracting the 10:45–11:00 break (BH-D107 L8) gives 45 min.
- **HG-E115 (2026-01-26, individual):** 40–50 min. The two notes disagree; see below.
- **HG-E118 (2026-01-29, group):** Rowan attended 10:00–11:30 (BH-D108 L12, L20). Subtracting the 10:45–11:00 break (BH-D107 L8) gives 75 min.
- **HG-E119 (2026-01-30, family):** Rowan was present 13:15–13:45 = 30 min. The partner was seen alone from 13:00 to 13:15 (BH-D113 L7, L11).

## What the records do not settle

- **HG-E115 (2026-01-26):** The two notes give different contact times, and neither corrects the other. The minutes are therefore carried as a range of 40–50. This is the only reason the overall total and the 2026-01-26 week are ranges.
  - BH-D110 records 09:00–09:50, 50 minutes (BH-D110 L7).
  - BH-D111 records 09:10–09:50, 40 minutes, and says Rowan entered the room at 09:10 (BH-D111 L7, L10).
- **HG-E119 (2026-01-30):** The note gives a therapist session time of 45 minutes (BH-D113 L6). Only the 30 minutes with Rowan present were counted. Whether 45 or 30 is the right figure depends on whether therapist time or patient-present time is the standard. The records do not decide that.

## Records excluded from the count

- **Not attended:**
  - HG-E103: no-show on 2026-01-08 (BH-D015 L11).
  - HG-E108: group cancelled by the clinic on 2026-01-15 (BH-D016 L9, L15).
  - HG-E116: no-show on 2026-01-27 (BH-D108 L10, L16).
  - HG-E117: cancelled by the patient on 2026-01-28 (BH-D108 L11).
- **HG-E116 draft and billing:** An unsigned template note says Rowan attended in full (BH-D112 L9, L11), and a charge for one group session was posted (BH-D112 L19, L22). Neither counts as evidence of attendance. The final roster's no-show was used instead.
- **Not therapy:**
  - Medication management: HG-E106 (BH-D010 L17) and HG-E120 (BH-D114 L12).
  - Partner-only collateral contact, with Rowan absent: HG-E109 (BH-D012 L8, L17).
  - Care coordination between professionals only: HG-E114 (BH-D109 L7).
  - Scheduling and outreach calls: BH-D015 L17, BH-D016 L15, BH-D108 L16.
  - Portal review and notice: BH-D013 L15, BH-D016 L11.
- **Copies:** BH-D104 is a resent copy of the 2026-01-19 roster that still shows a departure of 11:30. It is not independent evidence (BH-D104 L14, L20), and the correction to 11:15 applies to it as well.

The hours figures are the computed values as reported, rounded.

_Details, plan, calculations and evidence: [DEV-02.md](DEV-02.md)_

## DEV-03

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

_Details, plan, calculations and evidence: [DEV-03.md](DEV-03.md)_

## DEV-04

> Reconstruct the care on January 19 and January 21. How many therapy contacts and patient therapy minutes occurred on each date, and how do the attendance records, clinical notes, later documents, and telehealth records affect your answer?

**Answer.** On **January 19, 2026** there were **2 therapy contacts** and **90 patient therapy minutes (1.5 h)**: one group session of 60 min and one individual session of 30 min. On **January 21, 2026** there was **1 therapy contact** and **45 minutes (0.75 h)**: one individual video session. All of these totals are established, with no low–high range.

| Date | Encounter | Service / modality | Patient-present minutes | How the minutes were computed |
|---|---|---|---|---|
| Jan 19 | HG-E110 | Group therapy, in person (partial attendance) | 60 | 10:00–11:15, minus the break 10:45–11:00 |
| Jan 19 | HG-E111 | Individual therapy, in person | 30 | Stated contact 11:15–11:45 |
| **Jan 19 total** | | | **90** | |
| Jan 21 | HG-E112 | Individual therapy, video | 45 | 13:00–13:20 + 13:30–13:55 |
| **Jan 21 total** | | | **45** | |

**January 19: how each record affects the count**
- **Clinical note (BH-D101):** The note confirms the skills group took place on that date (BH-D101 L3). It records a scheduled time of 10:00–11:30 with a nontherapeutic break at 10:45–11:00 (BH-D101 L6). It says the patient's own arrival and departure are kept on the attendance roster (BH-D101 L10). The break is subtracted from the group minutes.
- **Original attendance roster (BH-D102):** The roster, signed Jan 19, lists arrival 10:00, departure 11:30 and status "Attended" (BH-D102 L4, L8–9). It notes the times were entered when the roster was closed (BH-D102 L12).
- **Later correction (BH-D103, signed Jan 20):** This changes the departure time to 11:15 and keeps arrival at 10:00 (BH-D103 L5, L7). It cites a room-transfer record showing the patient leaving skills room B at 11:15 and being received by the individual clinician at 11:15 (BH-D103 L9). The correction applies only to the departure field. It does not change the service date, the schedule, the break or the separate individual appointment (BH-D103 L11).
  - The software checked the correction against the individual session. The original 11:30 departure would have overlapped the 11:15–11:45 individual session; the corrected time does not.
  - The correction is the reason the group counts 60 minutes rather than a time based on the 11:30 departure. The group itself continued for other members until its scheduled close (BH-D103 L9).
- **Individual note (BH-D105):** This documents encounter HG-E111, in person on Jan 19, with contact 11:15–11:45, "Completed: 30 minutes" (BH-D105 L3, L5–6). The note says the patient took part throughout the contact (BH-D105 L11). BH-D103 does not name an encounter ID for this visit. It was matched to HG-E111 by date and service type.
- **Resent roster copy (BH-D104, received Jan 26):** This is a copy of the original roster, still showing departure 11:30 (BH-D104 L11, L13–14). It has no new clinician signature and records no additional visit (BH-D104 L20). It was **excluded as independent evidence** because it is a copy. Its 11:30 departure is also superseded by the BH-D103 correction. It adds no contact and no minutes.

**January 21: how the telehealth records affect the count**
- **Video session note (BH-D106):** The note, signed Jan 21 by Mira Patel, LCSW, records contact at 13:00–13:20 and 13:30–13:55, a total of 45 minutes (BH-D106 L5, L7). It states the connection was lost from 13:20 to 13:30 with no therapeutic contact during that time. It also states the reconnection continued the same encounter under the original appointment HG-A112 (BH-D106 L7).
- **Attached platform log:** The log shows calls VC-112A (13:00–13:20) and VC-112B (13:30–13:55), both under HG-A112 (BH-D106 L17–18). The second call is labelled "Rejoin original appointment after network disconnect" (BH-D106 L19). The export is dated Jan 21, 2026, 14:06 (BH-D106 L20).
  - The log's call times match the note's contact times. The second call is a rejoin of the same session, not a separate contact, so the day counts as **one** contact.
  - The disconnection interval is excluded from the minutes.
  - The log does not record an attendance status itself. Attendance rests on the clinical note.

**What the record does not settle / exclusions**
- There are no conflicts or uncertain encounters on either date.
- Excluded: BH-D104, a copy that is not independent evidence.
- Superseded: the 11:30 departure in BH-D102 and BH-D104.
- An undated observation from BH-D015 was rejected because the document states no date. The software lists it under every date for this patient, so it may not relate to these dates. It does not affect either day's count.
- These are factual counts of contacts and minutes. Apart from the patient-reported easing of anxiety in BH-D105 (BH-D105 L11), the results contain no statements about clinical outcomes.

_Details, plan, calculations and evidence: [DEV-04.md](DEV-04.md)_

## DEV-05

> Summarize the documented symptom course during the episode and the reason for the additional individual contact on January 19. Which symptom assessments are distinct, and what conclusions about progress can and cannot be supported?

# HG-M042 (Rowan): symptom course, 5–30 January 2026

## Direct answer
- **PHQ-9 scores:** three distinct PHQ-9s were recorded. The totals were 18 on 5 January (BH-D002 L15), 14 on 16 January (BH-D013 L7, L11) and 10 on 30 January, with item 9 scored 0 (BH-D115 L6).
- **Clinician judgement:** the treating clinician called this "partial improvement, with persistent avoidance and meaningful functional impact around returning to work" (BH-D115 L10).
- **Other symptoms:** sleep difficulty and anxiety about work were documented at every point through 30 January.
- **Why there was an extra contact on 19 January:** the individual visit (HG-E111) "was added because Rowan became anxious during group and needed individual grounding and review of coping strategies" (BH-D105 L9).

## Why the 19 January contact was added
- **In group (HG-E110):** Rowan first followed the exercise. When the talk turned to returning to the workplace, Rowan "became visibly tense and said the amount of discussion felt difficult to manage." The facilitator offered grounding and set up a same-day individual meeting (BH-D101 L10). Staff arranged access to the individual clinician after Rowan asked for more help (BH-D102 L14).
- **In the individual session:** Rowan said they felt overwhelmed when other members discussed work demands. Rowan named muscle tension, rapid breathing and an urge to leave as early signs of activation (BH-D105 L9). Rowan took part for the whole contact and said the anxiety "eased enough to discuss a next step" (BH-D105 L11).
- **Safety:** Rowan denied current suicidal thoughts and no acute safety concern was found (BH-D105 L13).
- **Timing:**
  - The group ran 10:00–11:15 with a break at 10:45–11:00, giving 60 minutes.
  - The individual contact ran 11:15–11:45, giving 30 minutes (BH-D105 L6).
  - The total for the day was 90 minutes.
  - A later correction changed the group departure time from 11:30 to 11:15 (BH-D103 L7). A room-transfer record shows Rowan going straight to the individual clinician at 11:15 (BH-D103 L9).

## Course by domain

| Date | PHQ-9 | Mood | Sleep | Anxiety / avoidance |
|---|---|---|---|---|
| Jan 5 (intake) | 18 (BH-D002 L15) | Low mood and reduced interest; affect subdued but responsive (BH-D002 L11, L13) | Fragmented; waking at night (BH-D002 L11, L13) | Worry about returning to work; putting off emails (BH-D002 L11) |
| Jan 13–14 | — | "Somewhat less heavy" on days with a planned activity (BH-D010 L11); affect more varied than at intake (BH-D011 L15) | Still interrupted (BH-D010 L11; BH-D011 L11) | Opened a work message but has not replied (BH-D011 L11) |
| Jan 16 | 14 (BH-D013 L7) | Clinician: "some improvement in depressive symptoms" (BH-D013 L13) | Inconsistent (BH-D013 L11) | Avoidance still clinically relevant (BH-D013 L13); partner says mornings are still difficult (BH-D012 L13) |
| Jan 19 | — | — | Disrupted (BH-D105 L13) | Anxiety in group led to the added visit (BH-D105 L9) |
| Jan 21–26 | — | Low mood ongoing (BH-D111 L14) | One better night, then a night of long wakefulness (BH-D106 L11); uneven (BH-D110 L9) | Drafted a message but did not send it (BH-D106 L9); later sent one, but kept putting off scheduling the conversation (BH-D110 L9) |
| Jan 30 | 10, item 9 = 0 (BH-D115 L6) | Fewer days of pervasive low mood than at intake (BH-D115 L8); less persistently low (BH-D114 L8) | Sleep difficulty continues (BH-D115 L8, L10); variable (BH-D114 L8) | Still delays follow-up (BH-D115 L10); anxiety still noticeable (BH-D114 L8) |

## Which assessments are distinct
- **Counted:** the three PHQ-9s above.
- **Not counted (copy):** BH-D014 is an imported summary received on 26 January. It restates the 16 January PHQ-9 (form HG-Q116, score 14) (BH-D014 L13), so it was not counted as a separate assessment. Its clinical comments repeat BH-D013 (BH-D014 L15).
- **Not assessments:** the other "measurement" entries in the results are restatements of these scores, not further administrations.

## What can be supported
- PHQ-9 totals fell across the three distinct administrations (18, then 14, then 10).
- Patients' reports and the clinician's notes agree that mood was less pervasively low by 30 January (BH-D115 L8; BH-D114 L8).
- The clinician's own conclusion is partial improvement (BH-D115 L10).
- The records show small behavioural steps: opening a message, short walks, and sending a message to the supervisor (BH-D011 L11; BH-D110 L9).

## What cannot be supported
- **Cause:** nothing in the record links the score changes to any specific treatment part (group, individual, family therapy or medication). The records give no reason for the change.
- **Resolution or recovery:** these are not documented. The clinician states that avoidance, sleep disruption and work-related functional impact persist, and that continued treatment is appropriate (BH-D115 L10, L12).
- **Item-level change:** item scores exist only for 30 January (item 9 = 0). The record does not show which symptoms drove the lower totals.
- **Better coping skills:** this should not be assumed. On 26 January Rowan could use the grounding cue in rehearsal but "remained uncertain about using it independently when anxious" (BH-D111 L12). The 19 January clinician warned that taking part in a group exercise should not be read as completing the patient's own work task (BH-D101 L12).
- **Reliable attendance:** this cannot be claimed.
  - A missed individual visit was discussed on 14 January (BH-D011 L15).
  - Rowan was absent from the 16 January contact, which only the partner attended (BH-D012 L11).
  - Rowan missed the whole 27 January group (BH-D108 L16) and cancelled the 28 January individual visit (BH-D108 L18).

## Records excluded or merged
- **BH-D014:** a copy of the 16 January PHQ-9, not counted separately.
- **BH-D104:** a resent copy (received 26 January) of the 19 January attendance list. It is not independent evidence and "records no additional visit" (BH-D104 L20).
- **BH-D102 departure time:** 11:30 was replaced by 11:15 under the correction in BH-D103 (BH-D103 L7).
- **BH-D015:** one observation was rejected because the document gives no date for it.
- **Partner and outside reports:** the partner's 16 January report (BH-D012) and the outside social worker's report (BH-D109) are second-hand accounts, not direct symptom observations.

_Details, plan, calculations and evidence: [DEV-05.md](DEV-05.md)_

