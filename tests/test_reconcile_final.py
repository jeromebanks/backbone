"""Reconciliation follow-ups #76, #77, #78, #80 and #81: hand-built claims, no LLM, no source documents.

Weeks are Mon–Sun; 2026-02-02 is a Monday.
"""
from __future__ import annotations

import copy
import itertools
import json
import random

import pytest

from backbone.db import connect
from backbone.ingest import build_claims
from backbone.query import CareStep, QueryPlan, Scope, execute_plan
from backbone.reconcile import Claim, persist, reconcile_patient
from backbone.schema import DocumentInfo, Extraction, ServiceEvent

from helpers import assessment, enc, event, relation, with_docs

WEEK = dict(start="2026-02-02", end="2026-02-08")
_n = itertools.count(9000)


# ---------------------------------------------------------------- builders

def build(tmp_path, claims, name="t.db"):
    conn = connect(tmp_path / name)
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('P1', 'Test', '1990-01-01')")
    res = reconcile_patient("P1", claims)
    with conn:
        persist(conn, res)
    return conn, res


def totals(conn, **scope):
    step = CareStep(scope=Scope(patients=["P1"], include_evidence=False, **{**WEEK, **scope}))
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]["totals"]


def bounds(t, metric):
    return t[metric]["low"], t[metric]["high"]


def corr(label, field, old, new, eid="E1") -> Claim:
    return relation(label, "corrects_field", eid=eid, field=field, old=old, new=new)


def ungrounded_event(label, grounding: dict, *, missing=False) -> Claim:
    """An unverified service event whose grounding entry records each value's status, as ingest writes it."""
    ev = event(label, stype="individual_therapy", contact=[("10:00", "10:30")], departure="11:30", verified=False)
    ev.evidence = [{"quote": "q", "line_start": None if missing else 4, "line_end": None if missing else 4,
                    "match": "missing" if missing else "exact"},
                   {"quote": None, "line_start": None, "line_end": None, "match": "grounding", "grounding": grounding}]
    return ev


def observation(label, *, quote, source, statement, date="2026-02-02", domain="anxiety", sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    return Claim(f"{sha}:observation:{next(_n)}", sha, label, "observation", date, None,
                 {"date": date, "domain": domain, "source": source, "statement": statement, "quote": quote}, [], True)


def r0_reasons(res) -> dict:
    return {d["claim_ids"][0]: d["reason"] for d in res.decisions if d["rule"] == "R0"}


# ---------------------------------------------------------------- #76 R0 reason for an ungrounded time or minutes

def test_ungrounded_departure_rejection_names_the_field():
    ev = ungrounded_event("NOTE", {"service_date": "quote", "patient_departure": "document",
                                   "patient_contact_intervals[0].start": "quote",
                                   "patient_contact_intervals[0].end": "quote"})
    reason = r0_reasons(reconcile_patient("P1", with_docs(ev)))[ev.claim_id]
    assert reason == ("NOTE service_event: the departure is not stated in the record's own quotes "
                      "(only elsewhere in the document)")
    assert "11:30" not in reason                    # an unverified value never reaches the results


def test_ungrounded_fields_of_both_kinds_are_each_named():
    ev = ungrounded_event("NOTE", {"service_date": "document", "patient_arrival": "absent",
                                   "stated_minutes": "absent", "patient_departure": "document",
                                   "nontherapeutic_intervals[0].end": "document"})
    reason = r0_reasons(reconcile_patient("P1", with_docs(ev)))[ev.claim_id]
    assert reason == ("NOTE service_event: the departure and non-therapeutic interval 1 end are not stated in the "
                      "record's own quotes (only elsewhere in the document); the arrival and minute total are not "
                      "stated anywhere in the document")
    assert "date" not in reason                     # a header-only service date is a flag, not a rejection (#36)


def test_missing_quote_still_says_quote_not_found():
    ev = ungrounded_event("NOTE", {"service_date": "quote", "patient_departure": "absent"}, missing=True)
    reason = r0_reasons(reconcile_patient("P1", with_docs(ev)))[ev.claim_id]
    assert reason == ("NOTE service_event: quote not found in source text; the departure is not stated anywhere in "
                      "the document")


GROUNDING_TEXT = ("Document ID: T-D1\n"
                  "Patient: Alex Doe | MRN ZZ-1\n"
                  "Encounter ZZ-E7 | Service date 2026-01-07\n"
                  "Individual therapy 10:00-10:30, completed.\n"
                  "Rowan left at 10:45.\n")


def test_ungrounded_departure_reason_end_to_end_from_build_claims():
    quote = "Individual therapy 10:00-10:30, completed."
    ex = Extraction(
        document=DocumentInfo(document_id="T-D1", title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name="Alex Doe", patient_mrn="ZZ-1", patient_dob=None,
                              relations=[]),
        service_events=[ServiceEvent(
            encounter_id="ZZ-E7", related_encounter_id=None, appointment_id=None, service_date="2026-01-07",
            service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
            disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
            patient_departure="10:45", patient_contact_intervals=[{"start": "10:00", "end": "10:30"}],
            nontherapeutic_intervals=[], stated_minutes=None, clinicians=[], quotes=[quote])],
        assessments=[], observations=[], plan_requirements=[])
    rows = build_claims("f" * 64, "T-D1", GROUNDING_TEXT, ex, "ZZ-1")
    claims = [Claim(r["claim_id"], r["sha256"], r["doc_label"], r["kind"], r["subject_key"], r["evidence_type"],
                    json.loads(r["payload"]), json.loads(r["evidence"]), bool(r["verified"])) for r in rows]
    res = reconcile_patient("ZZ-1", claims)
    (d,) = [d for d in res.decisions if d["rule"] == "R0"]
    assert d["reason"] == ("T-D1 service_event: the departure is not stated in the record's own quotes "
                           "(only elsewhere in the document)")


def test_absent_date_reason_is_unchanged():
    """#68's reason for an inferred date stays byte-identical (the corpus BH-D015 observation)."""
    ob = Claim("sha-n:observation:0", "sha-n", "NOTE", "observation", None, None,
               {"date": "2026-01-07", "domain": "sleep", "source": "patient_report", "statement": "s", "quote": "q"},
               [{"quote": "q", "line_start": 3, "line_end": 3, "match": "exact"},
                {"quote": None, "line_start": None, "line_end": None, "match": "grounding",
                 "grounding": {"date": "absent"}, "unverified_absent": ["date"]}], False)
    assert r0_reasons(reconcile_patient("P1", with_docs(ob)))[ob.claim_id] == (
        "NOTE observation: the date is not stated anywhere in the document (the extracted value was inferred)")


# ---------------------------------------------------------------- #77 R1 matching on corrected times

def test_idless_record_overlapping_only_the_corrected_interval_merges():
    claims = with_docs(
        event("note", stype="individual_therapy", contact=[("09:00", "09:20")]),
        corr("fix", "contact_interval", "09:00–09:20", "09:00–09:50"),
        event("register", eid=None, etype="attendance_record", stype="individual_therapy",
              arrival="09:30", departure="09:50"))
    for order in (claims, list(reversed(claims))):
        res = reconcile_patient("P1", copy.deepcopy(order))
        assert [e["encounter_key"] for e in res.encounters] == ["P1|E1"]
        assert any(d["outcome"] == "matched_without_id" for d in res.decisions)


def test_idless_record_overlapping_only_the_corrected_departure_merges():
    claims = with_docs(
        event("roster", etype="attendance_record", arrival="10:00", departure="10:20"),
        corr("fix", "departure", "10:20", "11:00"),
        event("note", eid=None, contact=[("10:30", "11:00")]))
    res = reconcile_patient("P1", claims)
    assert [e["encounter_key"] for e in res.encounters] == ["P1|E1"]


def test_correcting_documents_own_record_keeps_its_times_for_matching():
    """R3 never corrects the correcting document's own record, so R1 does not either."""
    claims = with_docs(
        event("corr-doc", etype="attendance_correction", arrival="10:00", departure="10:20", sha="sha-c"),
        relation("corr-doc", "corrects_field", eid="E1", field="departure", old="10:20", new="11:00", sha="sha-c"),
        event("note", eid=None, contact=[("10:30", "11:00")]))
    res = reconcile_patient("P1", claims)
    assert sorted(e["encounter_key"] for e in res.encounters) == ["P1|E1", "P1|U-2026-02-02-group_therapy-1"]


def test_uncorrected_times_still_match():
    """Every account counts: a resend of the uncorrected time is still the same contact (#61's union)."""
    claims = with_docs(
        event("roster", etype="attendance_record", arrival="10:00", departure="11:30"),
        corr("fix", "departure", "11:30", "11:15"),
        event("resend", eid=None, etype="attendance_record", arrival="11:20", departure="11:30"))
    res = reconcile_patient("P1", claims)
    assert [e["encounter_key"] for e in res.encounters] == ["P1|E1"]


# ---------------------------------------------------------------- #78 an ID-less record overlapping two contacts

def _two_contacts_and_a_group_record():
    return with_docs(
        event("note-ind", eid="E1", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("note-fam", eid="E2", stype="family_therapy", contact=[("10:50", "11:40")]),
        event("register", eid=None, stype="group_therapy", etype="attendance_record",
              arrival="10:40", departure="11:00"))


def test_idless_record_overlapping_two_contacts_adds_no_definite_session(tmp_path):
    conn, res = build(tmp_path, _two_contacts_and_a_group_record())
    assert not any(e["encounter_key"].startswith("P1|U-") for e in res.encounters), \
        [e["encounter_key"] for e in res.encounters]
    t = totals(conn)
    assert bounds(t, "sessions")[1] == 2, t                    # never a third session
    for eid, own in (("E1", "individual_therapy"), ("E2", "family_therapy")):   # either may be the group session
        rows = {e["service_type"]: e["eligible"] for e in res.encounters if e["encounter_id"] == eid}
        assert rows == {own: "uncertain", "group_therapy": "uncertain"}, rows
    grp = totals(conn, service_types=["group_therapy"])
    assert bounds(grp, "sessions") == (0, 2), grp
    # the one record placed in both is not "two contacts at once"; only accounts from different records are compared
    assert not any("10:40–11:00 vs P1|E2 10:40–11:00" in f for e in res.encounters for f in e["flags"])


def test_idless_record_overlapping_two_contacts_is_order_independent():
    claims = _two_contacts_and_a_group_record()
    want = None
    rng = random.Random(78)
    for _ in range(10):
        shuffled = copy.deepcopy(claims)
        rng.shuffle(shuffled)
        res = reconcile_patient("P1", shuffled)
        got = json.dumps([{k: v for k, v in e.items() if not k.startswith("_")} for e in res.encounters]
                         + res.decisions + res.conflicts, sort_keys=True, default=str)
        assert want is None or got == want
        want = got


def test_ambiguous_same_type_record_is_not_a_definite_session(tmp_path):
    """Two group sessions on one day and an ID-less group record that names no times: it is one of them or a third
    session, so it counts within bounds only."""
    conn, res = build(tmp_path, with_docs(
        event("note-a", eid="E1", contact=[("09:00", "09:50")]),
        event("note-b", eid="E2", contact=[("14:00", "14:50")]),
        event("listing", eid=None, etype="schedule_listing")))
    (u,) = [e for e in res.encounters if e["encounter_key"].startswith("P1|U-")]
    assert u["eligible"] == "uncertain", u
    assert bounds(totals(conn), "sessions") == (2, 3)


# ---------------------------------------------------------------- #80 assessments and observations

def test_disagreeing_primary_scores_give_a_conflict_and_no_definite_score():
    claims = with_docs(assessment("portal", score=14, date="2026-02-02", form_id="F1"),
                       assessment("clinic", score=15, date="2026-02-02", form_id="F1"))
    for order in (claims, list(reversed(claims))):
        res = reconcile_patient("P1", copy.deepcopy(order))
        (a,) = res.assessments
        assert (a["status"], a["total_score"]) == ("disputed", None), a
        (c,) = [c for c in res.conflicts if c["field"] == "total_score"]
        assert [x["value"] for x in c["candidates"]] == [14, 15]
        assert any(d["rule"] == "R8" and d["outcome"] == "score_disputed" for d in res.decisions)


def test_a_record_without_a_score_is_silent_not_a_disagreement():
    claims = with_docs(assessment("portal", score=None, date="2026-02-02", form_id="F1", sha="sha-a"),
                       assessment("clinic", score=14, date="2026-02-02", form_id="F1", sha="sha-b"))
    (a,) = reconcile_patient("P1", claims).assessments
    assert (a["status"], a["total_score"]) == ("distinct", 14)


def test_a_differing_copy_does_not_change_the_primary_score():
    claims = with_docs(assessment("portal", score=14, date="2026-02-02", form_id="F1"),
                       assessment("import", score=15, date="2026-02-02", form_id="F1", copy=True))
    res = reconcile_patient("P1", claims)
    (a,) = res.assessments
    assert (a["status"], a["total_score"]) == ("distinct", 14)
    (d,) = [d for d in res.decisions if d["outcome"] == "copy_not_distinct"]
    assert "states total score 15" in d["reason"]


def test_one_form_under_two_instruments_is_an_instrument_conflict():
    a = assessment("portal", score=14, date="2026-02-02", form_id="F1")
    b = assessment("clinic", score=14, date="2026-02-02", form_id="F1")
    b.payload["instrument"] = "GAD-7"
    res = reconcile_patient("P1", with_docs(a, b))
    assert {x["status"] for x in res.assessments} == {"disputed"}
    cs = [c for c in res.conflicts if c["field"] == "instrument"]           # one per reading's row
    assert sorted(c["subject_key"] for c in cs) == sorted(x["assessment_key"] for x in res.assessments)
    assert all([x["value"] for x in c["candidates"]] == ["GAD-7", "PHQ-9"] for c in cs)


def test_two_instruments_on_one_day_without_a_shared_form_are_two_assessments():
    a = assessment("portal", score=14, date="2026-02-02")
    b = assessment("clinic", score=9, date="2026-02-02")
    b.payload["instrument"] = "GAD-7"
    res = reconcile_patient("P1", with_docs(a, b))
    assert sorted((x["instrument"], x["status"], x["total_score"]) for x in res.assessments) == [
        ("GAD-7", "distinct", 9), ("PHQ-9", "distinct", 14)]
    assert not res.conflicts


def test_one_quote_with_two_statements_keeps_both():
    q = "Rowan became visibly tense and said the discussion felt difficult to manage."
    claims = with_docs(observation("NOTE", quote=q, source="clinician_observation", statement="Patient became tense."),
                       observation("NOTE", quote=q, source="patient_report", statement="Patient said it felt difficult."))
    res = reconcile_patient("P1", claims)
    assert sorted((o["source"], o["statement"]) for o in res.observations) == [
        ("clinician_observation", "Patient became tense."), ("patient_report", "Patient said it felt difficult.")]


def test_a_restated_observation_is_still_one_row():
    q = "Rowan reported sleeping poorly."
    claims = with_docs(observation("NOTE", quote=q, source="patient_report", statement="Poor sleep."),
                       observation("NOTE", quote=q, source="patient_report", statement="Poor sleep."))
    assert len(reconcile_patient("P1", claims).observations) == 1


# ---------------------------------------------------------------- #81 modality

def test_disagreeing_tier1_modality_is_disputed_with_a_conflict():
    a = event("note", stype="individual_therapy", contact=[("09:00", "09:50")])
    b = event("log", stype="individual_therapy", etype="platform_log", contact=[("09:00", "09:50")])
    b.payload["modality"] = "video"
    for order in ([a, b], [b, a]):
        res = reconcile_patient("P1", with_docs(*copy.deepcopy(order)))
        e = enc(res)
        assert e["modality"] == "disputed", e
        (c,) = [c for c in res.conflicts if c["field"] == "modality"]
        assert [x["value"] for x in c["candidates"]] == ["in_person", "video"]


def test_agreeing_modality_and_unknown_silence():
    a = event("note", stype="individual_therapy", contact=[("09:00", "09:50")])
    b = event("register", stype="individual_therapy", etype="attendance_record", arrival="09:00", departure="09:50")
    b.payload["modality"] = "unknown"
    res = reconcile_patient("P1", with_docs(a, b))
    assert enc(res)["modality"] == "in_person" and not [c for c in res.conflicts if c["field"] == "modality"]


def test_tier1_modality_decides_over_a_listing():
    a = event("note", stype="individual_therapy", contact=[("09:00", "09:50")])
    b = event("listing", stype="individual_therapy", etype="schedule_listing", scheduled=("09:00", "09:50"))
    b.payload["modality"] = "video"
    res = reconcile_patient("P1", with_docs(a, b))
    assert enc(res)["modality"] == "in_person" and not [c for c in res.conflicts if c["field"] == "modality"]
