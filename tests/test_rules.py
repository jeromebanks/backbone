"""Reconciliation rules on hand-built claims (no LLM, no database)."""
from backbone.evidence import DocumentIndex
from backbone.intervals import normalize, subtract, to_min, total
from backbone.project import consecutive_runs, evaluate_requirement
from backbone.reconcile import reconcile_patient

from helpers import assessment, doc, enc, event, relation, with_docs

GROUP = ("10:00", "11:30")
BREAK = [("10:45", "11:00", "break")]


# ---------------------------------------------------------------- interval algebra

def test_interval_algebra():
    a = [(to_min("10:00"), to_min("11:30"))]
    b = [(to_min("10:45"), to_min("11:00"))]
    assert total(subtract(a, b)) == 75
    assert normalize([(0, 10), (5, 20), (30, 40)]) == [(0, 20), (30, 40)]
    assert total(subtract([(0, 10)], [(0, 10)])) == 0


# ---------------------------------------------------------------- evidence

def test_quote_verification_rejects_fabrication():
    text = "Line one\nPatient contact: 11:15–11:45 | Completed: 30 minutes\nLine three"
    idx = DocumentIndex(text)
    s = idx.locate("Patient contact: 11:15-11:45")          # dash variant still matches
    assert s.match in ("exact", "normalized") and s.line_start == 2
    assert idx.locate("Patient contact: 11:00-12:30 | Completed: 90 minutes").match == "missing"


def test_unverified_claims_are_excluded():
    res = reconcile_patient("P1", with_docs(
        event("A", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP, verified=False),
    ))
    assert res.encounters == []
    assert any(d["rule"] == "R0" for d in res.decisions)


# ---------------------------------------------------------------- R3 corrections vs retransmissions

def test_field_correction_beats_later_retransmission():
    claims = with_docs(
        event("note", etype="clinical_note", scheduled=GROUP, nontherapeutic=BREAK),
        event("roster", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        event("correction", etype="attendance_correction", arrival="10:00", departure="11:15"),
        relation("correction", "corrects_field", eid="E1", field="departure", old="11:30", new="11:15"),
        # received a week later, still showing the uncorrected value
        event("resent", etype="retransmitted_copy", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("resent", "retransmits_original", eid="E1"),
    )
    e = enc(reconcile_patient("P1", claims))
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (60, 60, "established")


# ---------------------------------------------------------------- R2 drafts / billing

def test_draft_and_charge_do_not_override_signed_register():
    claims = with_docs(
        event("register", etype="attendance_record", disposition="no_show", present="no", scheduled=GROUP),
        event("draft", etype="draft_template", disposition="attended_full", scheduled=GROUP, sha="sha-x"),
        event("charge", etype="billing", disposition="unknown", present="unknown", sha="sha-x"),
    )
    claims.append(doc("draft", finality="draft", signed=False, sha="sha-x"))
    e = enc(reconcile_patient("P1", claims))
    assert e["eligible"] == "no" and e["attended"] == "no"


# ---------------------------------------------------------------- R6 minutes

def test_two_connections_one_encounter():
    claims = with_docs(
        event("video", stype="individual_therapy", contact=[("13:00", "13:20"), ("13:30", "13:55")],
              nontherapeutic=[("13:20", "13:30", "disconnection")], stated=45),
        event("video", stype="individual_therapy", etype="platform_log", disposition="unknown", present="unknown"),
    )
    res = reconcile_patient("P1", claims)
    assert len(res.encounters) == 1
    e = res.encounters[0]
    assert (e["minutes_low"], e["eligible"]) == (45, "yes")


def test_partner_only_portion_excluded():
    e = enc(reconcile_patient("P1", with_docs(
        event("fam", stype="family_therapy", disposition="attended_partial", present="partial",
              contact=[("13:15", "13:45")], nontherapeutic=[("13:00", "13:15", "patient_absent")], stated=45))))
    assert e["minutes_low"] == 30 and any("states 45" in f for f in e["flags"])


def test_late_arrival_and_break():
    e = enc(reconcile_patient("P1", with_docs(
        event("note", scheduled=GROUP, nontherapeutic=BREAK),
        event("register", etype="attendance_record", arrival="10:30", departure="11:30", scheduled=GROUP))))
    assert e["minutes_low"] == 45


def test_conflicting_signed_notes_become_bounds():
    e = enc(reconcile_patient("P1", with_docs(
        event("primary", stype="individual_therapy", contact=[("09:00", "09:50")], stated=50),
        event("second", stype="individual_therapy", contact=[("09:10", "09:50")], stated=40))))
    assert (e["minutes_low"], e["minutes_high"], e["minutes_status"]) == (40, 50, "disputed")


def test_missing_departure_is_unknown_not_zero():
    e = enc(reconcile_patient("P1", with_docs(
        event("note", scheduled=GROUP, nontherapeutic=BREAK),
        event("register", etype="attendance_record", arrival="10:00", departure=None, scheduled=GROUP))))
    assert e["eligible"] == "yes" and e["minutes_status"] == "unknown"
    assert (e["minutes_low"], e["minutes_high"]) == (0, 75)


def test_unknown_attendance_is_uncertain():
    e = enc(reconcile_patient("P1", with_docs(
        event("schedule", etype="schedule_listing", disposition="scheduled_only", present="unknown",
              scheduled=GROUP))))
    assert e["eligible"] == "uncertain"


def test_collateral_and_med_management_do_not_count():
    res = reconcile_patient("P1", with_docs(
        event("coll", eid="E1", stype="family_collateral", present="no", contact=[("14:00", "14:40")]),
        event("med", eid="E2", stype="medication_management", contact=[("09:00", "09:25")])))
    assert {e["eligible"] for e in res.encounters} == {"no"}


# ---------------------------------------------------------------- R1 identity

def test_event_without_id_matches_by_date_and_type():
    res = reconcile_patient("P1", with_docs(
        event("note", eid="E9", stype="individual_therapy", contact=[("11:15", "11:45")]),
        event("mention", eid=None, stype="individual_therapy", etype="other", disposition="unknown",
              present="unknown")))
    assert len(res.encounters) == 1


def test_duplicate_companion_notes_one_session():
    res = reconcile_patient("P1", with_docs(
        event("primary", stype="family_therapy", contact=[("14:00", "14:45")]),
        event("cofac", stype="family_therapy", contact=[("14:00", "14:45")])))
    assert len(res.encounters) == 1 and res.encounters[0]["minutes_low"] == 45


# ---------------------------------------------------------------- R8 assessments

def test_imported_copy_is_not_a_new_assessment():
    res = reconcile_patient("P1", with_docs(
        assessment("portal", score=14, date="2026-01-16", form_id="Q1"),
        assessment("import", score=14, date="2026-01-16", form_id="Q1", copy=True),
        assessment("intake", score=18, date="2026-01-05")))
    assert len(res.assessments) == 2
    a = next(a for a in res.assessments if a["form_id"] == "Q1")
    assert a["copy_claim_ids"] and a["status"] == "distinct"


# ---------------------------------------------------------------- compliance semantics

def _req(metric, thr):
    return {"requirement_key": metric, "metric": metric, "comparator": ">=", "threshold": thr}


def test_three_valued_compliance():
    totals = {"therapy_days": {"low": 3, "high": 3}, "minutes": {"low": 145, "high": 155}, "sessions": {"low": 3, "high": 3}}
    assert evaluate_requirement(_req("therapy_days", 3), totals)["status"] == "MET"
    assert evaluate_requirement(_req("patient_present_minutes", 150), totals)["status"] == "UNDETERMINED"
    totals["minutes"] = {"low": 140, "high": 140}
    assert evaluate_requirement(_req("patient_present_minutes", 150), totals)["status"] == "NOT_MET"
    totals["minutes"] = {"low": 0, "high": None}           # unbounded unknown never becomes NOT_MET
    assert evaluate_requirement(_req("patient_present_minutes", 150), totals)["status"] == "UNDETERMINED"


def test_consecutive_runs_distinguish_unresolved():
    weeks = [{"week_start": f"w{i}", "status": s} for i, s in enumerate(["NOT_MET", "UNDETERMINED", "MET"])]
    r = consecutive_runs(weeks, 2)
    assert r["status"] == "depends_on_unresolved"
    weeks[1]["status"] = "NOT_MET"
    assert consecutive_runs(weeks, 2)["status"] == "yes"
