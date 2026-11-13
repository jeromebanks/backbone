"""Encounter identity (R1), eligibility (R5) and minutes (R6) on hand-built claims (no LLM, no source documents).

Each test reproduces one reported issue (#11, #12, #13, #17). Weeks are Mon–Sun; 2026-02-02 is a Monday.
"""
import itertools

import pytest

from backbone.db import connect
from backbone.query import CareStep, ComplianceStep, QueryPlan, Scope, execute_plan
from backbone.reconcile import Claim, persist, reconcile_patient

from helpers import event, with_docs

NOTE = dict(stype="individual_therapy", disposition="attended_full")
ALL_THERAPY = ["individual_therapy", "group_therapy", "family_therapy"]
_n = itertools.count()


def plan(label, metric, threshold, *, counted=ALL_THERAPY, start="2026-02-02", end="2026-02-28") -> Claim:
    sha = f"sha-{label}"
    payload = {"metric": metric, "threshold": float(threshold), "comparator": ">=", "period": "week_mon_sun",
               "counted_service_types": list(counted), "excluded_service_types": [],
               "requires_patient_present": True, "effective_start": start, "effective_end": end, "quote": "q"}
    return Claim(f"{sha}:plan_requirement:{next(_n)}", sha, label, "plan_requirement", None, None, payload, [], True)


def build(tmp_path, claims):
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('P1', 'Test', '1990-01-01')")
    res = reconcile_patient("P1", claims)
    with conn:
        persist(conn, res)
    return conn, res


def weeks(conn, start, end):
    step = ComplianceStep(scope=Scope(patients=["P1"], start=start, end=end, include_evidence=False))
    return {g["week_start"]: g for g in execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]["groups"]}


def sessions(week):
    return [r["value"] for ev in week["evaluations"] for r in ev["requirements"] if r["metric"] == "sessions"]


# ---------------------------------------------------------------- #11 ID-less contacts with disjoint actual times

def test_disjoint_idless_sessions_stay_two_encounters():
    res = reconcile_patient("P1", with_docs(
        event("morning", eid=None, etype="attendance_record", arrival="09:00", departure="09:30"),
        event("afternoon", eid=None, etype="attendance_record", arrival="15:00", departure="15:45")))
    assert len(res.encounters) == 2
    assert sorted((e["minutes_low"], e["minutes_high"], e["minutes_status"]) for e in res.encounters) == [
        (30, 30, "established"), (45, 45, "established")]


def test_idless_record_with_disjoint_times_is_not_matched_to_an_identified_encounter():
    res = reconcile_patient("P1", with_docs(
        event("register", eid="E1", etype="attendance_record", arrival="09:00", departure="09:30"),
        event("note", eid=None, arrival="15:00", departure="15:45")))
    assert len(res.encounters) == 2


def test_idless_record_with_overlapping_times_still_matches():
    res = reconcile_patient("P1", with_docs(
        event("note", eid="E1", scheduled=("10:00", "11:30"), nontherapeutic=[("10:45", "11:00", "break")]),
        event("register", eid=None, etype="attendance_record", arrival="10:30", departure="11:30")))
    assert len(res.encounters) == 1
    assert res.encounters[0]["minutes_low"] == 45


# ---------------------------------------------------------------- #12 disputed service type or date

def test_service_type_tie_between_therapy_and_non_therapy_is_uncertain():
    res = reconcile_patient("P1", with_docs(
        event("note-a", stype="individual_therapy", contact=[("09:00", "10:00")]),
        event("note-b", stype="medication_management", contact=[("09:00", "10:00")])))
    assert len(res.encounters) == 1
    e = res.encounters[0]
    assert e["eligible"] == "uncertain", e
    assert any(c["field"] == "service_type" and c["resolution"] == "disputed" for c in res.conflicts)


def test_service_type_majority_does_not_decide():
    """Two notes against one is still a disagreement between signed tier-1 records (no majority rule)."""
    res = reconcile_patient("P1", with_docs(
        event("note-a", stype="individual_therapy", contact=[("09:00", "10:00")]),
        event("note-b", stype="individual_therapy", contact=[("09:00", "10:00")]),
        event("note-c", stype="medication_management", contact=[("09:00", "10:00")])))
    assert res.encounters[0]["eligible"] == "uncertain"


@pytest.mark.parametrize("counted", [["group_therapy"], ["individual_therapy"]])
def test_service_type_dispute_between_therapy_types_reaches_per_type_goals(tmp_path, counted):
    """Whichever type the representative row carries, a goal counting the other type is not NOT_MET."""
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=counted),
        event("note-a", stype="individual_therapy", date="2026-02-03", contact=[("09:00", "10:00")]),
        event("note-b", stype="group_therapy", date="2026-02-03", contact=[("09:00", "10:00")])))
    w = weeks(conn, "2026-02-02", "2026-02-08")["2026-02-02"]
    assert [(v["low"], v["high"]) for v in sessions(w)] == [(0, 1)]
    assert w["status"] == "UNDETERMINED"
    assert not any("overlap" in f for e in res.encounters for f in e["flags"])   # siblings are one encounter (R7)


def test_service_date_tie_widens_both_weeks(tmp_path):
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1),
        event("note-a", date="2026-02-08", contact=[("09:00", "09:50")], **NOTE),
        event("note-b", date="2026-02-09", contact=[("09:00", "09:50")], **NOTE)))
    ws = weeks(conn, "2026-02-02", "2026-02-15")
    assert [(v["low"], v["high"]) for v in sessions(ws["2026-02-02"])] == [(0, 1)]
    assert [(v["low"], v["high"]) for v in sessions(ws["2026-02-09"])] == [(0, 1)]
    assert {ws[k]["status"] for k in ws} == {"UNDETERMINED"}
    assert any(c["field"] == "service_date" and c["resolution"] == "disputed" for c in res.conflicts)


def test_service_date_dispute_counts_once_over_a_range_covering_every_alternative(tmp_path):
    """Guard (passes before the fix too): alternative rows of one encounter never add up to more than one session.
    The bounds are sound but not tight: the projection cannot tell that every alternative is in range."""
    conn, _ = build(tmp_path, with_docs(
        event("note-a", date="2026-02-08", contact=[("09:00", "09:50")], **NOTE),
        event("note-b", date="2026-02-09", contact=[("09:00", "09:50")], **NOTE)))
    step = CareStep(scope=Scope(patients=["P1"], start="2026-02-01", end="2026-02-28", include_evidence=False))
    totals = execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]["totals"]
    for k, truth in (("sessions", 1), ("minutes", 50), ("therapy_days", 1)):
        assert totals[k]["low"] <= truth <= totals[k]["high"], (k, totals[k])
    assert totals["sessions"]["high"] == 1 and totals["minutes"]["high"] == 50


# ---------------------------------------------------------------- #13 conflicting exclusions

def test_disagreeing_break_windows_are_a_dispute_not_a_double_subtraction():
    res = reconcile_patient("P1", with_docs(
        event("note-a", contact=[("10:00", "11:00")], nontherapeutic=[("10:15", "10:30", "break")]),
        event("note-b", contact=[("10:00", "11:00")], nontherapeutic=[("10:30", "10:45", "break")])))
    e = res.encounters[0]
    assert (e["minutes_low"], e["minutes_high"]) == (45, 45), e
    assert e["minutes_status"] == "disputed"
    assert any(c["field"] == "nontherapeutic_intervals" for c in res.conflicts)


def test_disagreeing_breaks_of_different_length_give_bounds():
    e = reconcile_patient("P1", with_docs(
        event("note-a", contact=[("10:00", "11:00")], nontherapeutic=[("10:15", "10:30", "break")]),
        event("note-b", contact=[("10:00", "11:00")], nontherapeutic=[("10:30", "10:35", "break")]))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 55, "disputed")


def test_a_record_silent_about_breaks_does_not_dispute_one_that_states_them():
    e = reconcile_patient("P1", with_docs(
        event("note", scheduled=("10:00", "11:30"), nontherapeutic=[("10:45", "11:00", "break")]),
        event("register", etype="attendance_record", arrival="10:15", departure="11:15"))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 45, "established")


def test_different_kinds_of_exclusion_both_apply():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("13:00", "14:00")], nontherapeutic=[("13:20", "13:30", "break")]),
        event("log", etype="platform_log", contact=[("13:00", "14:00")],
              nontherapeutic=[("13:40", "13:45", "disconnection")]))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 45, "established")


def test_lower_tier_exclusion_does_not_override_tier_one():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("10:00", "11:00")], nontherapeutic=[("10:45", "11:00", "break")]),
        event("schedule", etype="schedule_listing", disposition="attended", scheduled=("10:00", "11:00"),
              nontherapeutic=[("10:15", "10:30", "break")]))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 45, "established")


def test_lower_tier_exclusion_applies_when_tier_one_is_silent():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("10:00", "11:00")]),
        event("schedule", etype="schedule_listing", disposition="attended", scheduled=("10:00", "11:00"),
              nontherapeutic=[("10:15", "10:30", "break")]))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 45, "established")


# ---------------------------------------------------------------- #17 overnight / inverted intervals

def test_overnight_scheduled_session_is_unknown_not_zero():
    e = reconcile_patient("P1", with_docs(
        event("note", scheduled=("23:30", "00:30"), **NOTE))).encounters[0]
    assert e["minutes_status"] == "unknown", e
    assert (e["minutes_low"], e["minutes_high"]) == (0, None)
    assert any("overnight" in f or "inverted" in f for f in e["flags"])


def test_overnight_contact_interval_is_unknown_not_zero():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("23:30", "00:30")], **NOTE))).encounters[0]
    assert e["minutes_status"] == "unknown", e
    assert (e["minutes_low"], e["minutes_high"]) == (0, None)
    assert any("overnight" in f for f in e["flags"])


def test_inverted_schedule_does_not_spoil_a_valid_contact_interval():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("23:00", "23:45")], scheduled=("23:30", "00:30"), **NOTE))).encounters[0]
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (45, 45, "established"), e
    assert any("overnight" in f for f in e["flags"])


def test_partly_overnight_contact_set_is_not_truncated():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("23:00", "23:30"), ("23:45", "00:15")], **NOTE))).encounters[0]
    assert e["minutes_status"] == "unknown" and e["minutes_high"] is None, e


def test_overnight_arrival_departure_is_unknown_not_zero():
    e = reconcile_patient("P1", with_docs(
        event("register", etype="attendance_record", arrival="23:30", departure="00:30",
              scheduled=("23:30", "00:30")))).encounters[0]
    assert e["minutes_status"] == "unknown" and (e["minutes_low"], e["minutes_high"]) == (0, None), e


def test_inverted_exclusion_is_flagged_and_widens_the_low_bound():
    e = reconcile_patient("P1", with_docs(
        event("note", contact=[("10:00", "11:00")], nontherapeutic=[("10:45", "10:30", "break")]))).encounters[0]
    assert e["minutes_status"] == "unknown" and (e["minutes_low"], e["minutes_high"]) == (0, 60), e
    assert any("inverted" in f for f in e["flags"])
