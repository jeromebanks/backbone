"""Evidence grounding: claims need real quotes (#14), fuzzy matches can't change numbers (#15), and the answer
post-check can't be satisfied by the question text, uncited documents or partially covered ranges (#16).
No LLM, no extraction cache: hand-built extractions and a temp DB."""
from __future__ import annotations

import json

from backbone.answer import postcheck
from backbone.db import connect
from backbone.evidence import DocumentIndex
from backbone.ingest import build_claims
from backbone.reconcile import Claim, reconcile_patient
from backbone.schema import DocumentInfo, Extraction, PlanRequirement, ServiceEvent

TEXT = ("Document ID: T-D1\n"
        "Patient: Alex Doe | MRN ZZ-1\n"
        "Encounter ZZ-E7 | Service date 2026-01-07\n"
        "Individual therapy 10:00-10:30, completed.\n"
        "Treatment plan: at least 3 therapy days per week.\n")


def _event(quotes, nontherapeutic=()):
    return ServiceEvent(
        encounter_id="ZZ-E7", related_encounter_id=None, appointment_id=None, service_date="2026-01-07",
        service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
        disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
        patient_departure=None, patient_contact_intervals=[{"start": "10:00", "end": "10:30"}],
        nontherapeutic_intervals=list(nontherapeutic), stated_minutes=None, clinicians=[], quotes=quotes)


def _plan(quote):
    return PlanRequirement(metric="therapy_days", threshold=3, comparator=">=", period="week_mon_sun",
                           counted_service_types=["individual_therapy"], excluded_service_types=[],
                           requires_patient_present=True, effective_start="2026-01-05", effective_end=None,
                           quote=quote)


def _extraction(events=(), plans=()):
    return Extraction(
        document=DocumentInfo(document_id="T-D1", title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name="Alex Doe", patient_mrn="ZZ-1", patient_dob=None,
                              relations=[]),
        service_events=list(events), assessments=[], observations=[], plan_requirements=list(plans))


def _claims(ex):
    rows = build_claims("f" * 64, "T-D1", TEXT, ex, "ZZ-1")
    return rows, [Claim(r["claim_id"], r["sha256"], r["doc_label"], r["kind"], r["subject_key"], r["evidence_type"],
                        json.loads(r["payload"]), json.loads(r["evidence"]),
                        bool(r["verified"])) for r in rows]


def _r0_rejected(claims):
    res = reconcile_patient("ZZ-1", claims)
    return {cid for d in res.decisions if d["rule"] == "R0" for cid in d["claim_ids"]}


# ---------------------------------------------------------------- #14 claims without supporting quotes

def test_quoted_event_is_verified_control():
    rows, claims = _claims(_extraction([_event(["Individual therapy 10:00-10:30, completed."])]))
    ev = next(r for r in rows if r["kind"] == "service_event")
    assert ev["verified"] == 1
    assert not _r0_rejected(claims)


def test_event_without_quotes_is_rejected_by_r0():
    for quotes in ([], [""], ["   "]):
        rows, claims = _claims(_extraction([_event(quotes)]))
        ev = next(r for r in rows if r["kind"] == "service_event")
        assert ev["verified"] == 0, quotes
        assert ev["claim_id"] in _r0_rejected(claims), quotes


def test_event_supported_only_by_a_nontherapeutic_quote_is_rejected():
    # The break quote is real, but it says nothing about the event's date, times or attendance.
    nt = {"start": "10:10", "end": "10:15", "kind": "break", "quote": "Individual therapy 10:00-10:30"}
    rows, claims = _claims(_extraction([_event([], nontherapeutic=[nt])]))
    ev = next(r for r in rows if r["kind"] == "service_event")
    assert ev["verified"] == 0
    assert ev["claim_id"] in _r0_rejected(claims)


def test_plan_requirement_with_blank_quote_is_rejected():
    rows, claims = _claims(_extraction(plans=[_plan("")]))
    pr = next(r for r in rows if r["kind"] == "plan_requirement")
    assert pr["verified"] == 0
    assert pr["claim_id"] in _r0_rejected(claims)


def test_document_claim_stays_verified():
    rows, _ = _claims(_extraction())
    assert next(r for r in rows if r["kind"] == "document")["verified"] == 1


# ---------------------------------------------------------------- #15 fuzzy matching must not change numbers

FUZZ_TEXT = "Header line\nGroup session 10:00-10:30 local, patient attended throughout the session.\nFooter\n"


def test_fuzzy_match_rejects_changed_digits():
    idx = DocumentIndex(FUZZ_TEXT)
    assert idx.locate("Group session 10:00-11:30 local, patient attended throughout the session.").match == "missing"
    assert idx.locate("Group session 10:00-10:30 local, patient attended throughout the session.").match == "exact"


def test_fuzzy_match_rejects_changed_identifier():
    text = "Header\nEncounter HG-E110 group session, patient attended throughout the session.\n"
    assert DocumentIndex(text).locate(
        "Encounter HG-E111 group session, patient attended throughout the session.").match == "missing"


def test_fuzzy_match_still_tolerates_prose_typos():
    idx = DocumentIndex(FUZZ_TEXT)
    s = idx.locate("Group sesion 10:00-10:30 local, patient atended throughout the session.")
    assert s.match == "fuzzy" and s.line_start == 2


# ---------------------------------------------------------------- #16 post-check false successes

PC_DOC = "\n".join(f"line {i}" for i in range(1, 13))


def _pc_conn(tmp_path):
    conn = connect(tmp_path / "pc.db")
    for sha, label in (("a" * 64, "T-D1"), ("b" * 64, "T-D2")):
        conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) "
                     "VALUES (?,?,?,?,?,?)", (sha, label, "[]", PC_DOC, "ZZ-1", "2026-01-01T00:00:00"))
    conn.commit()
    return conn


def _results(question="How many minutes?", passages=("1", "10")):
    return {"question": question, "plan": {"question": question, "steps": []}, "results": [{
        "op": "care", "totals": {"minutes": {"low": 50, "high": 50}, "sessions": 1},
        "calculation": ["ZZ-E7: 10:00-10:50 = 50 min"],
        "evidence": [{"claim_id": "x", "doc_id": "T-D1", "file": "t.txt", "record_type": "clinical_note",
                      "passages": [{"lines": p, "quote": f"line {p}"} for p in passages]}],
        "sql": "SELECT 9999"}]}


def test_postcheck_accepts_a_correctly_cited_answer(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes over 1 session (T-D1 L1; T-D1 L10).", _results())
    assert pc["ok"], pc


def test_postcheck_rejects_number_only_in_question(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 9999 minutes (T-D1 L1).", _results(question="Was it 9999 minutes?"))
    assert pc["numbers_not_in_results"] == ["9999"] and not pc["ok"]


def test_postcheck_rejects_document_not_in_results(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes (T-D1 L1). See also T-D2.", _results())
    assert pc["documents_not_in_results"] == ["T-D2"] and not pc["ok"]


def test_postcheck_document_named_only_in_question_is_not_in_results(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes (T-D1 L1). See also T-D2.",
                   _results(question="Does T-D2 matter?"))
    assert pc["documents_not_in_results"] == ["T-D2"] and not pc["ok"]


def test_postcheck_rejects_partially_covered_range(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes (T-D1 L1–10).", _results())
    assert "T-D1 L2" in pc["line_refs_outside_evidence"] and not pc["ok"]


def test_postcheck_accepts_range_covered_by_adjacent_passages(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes (T-D1 L1–3).", _results(passages=("1-2", "3")))
    assert pc["ok"], pc


def test_postcheck_rejects_reversed_range(tmp_path):
    pc = postcheck(_pc_conn(tmp_path), "Total 50 minutes (T-D1 L10–1).", _results())
    assert not pc["ok"]


def test_exact_match_must_not_start_or_end_inside_a_number():
    text = "Header\nGroup completed: 45 minutes total, patient attended throughout the whole session.\nEnd\n"
    idx = DocumentIndex(text)
    assert idx.locate("5 minutes total, patient attended").match == "missing"
    assert idx.locate("Group completed: 4").match == "missing"
    assert idx.locate("45 minutes total, patient attended").match == "exact"
    assert idx.locate("5 minutes total, patient ... attended throughout the whole").match == "missing"
    assert idx.locate("45 minutes total, patient ... attended throughout the whole").match == "normalized"


def test_fuzzy_match_tolerates_spacing_around_dashes():
    text = "Header\nIndividual therapy 10:00–10:30 local, patient attended throughout the session.\n"
    s = DocumentIndex(text).locate("Individual therapy 10:00 – 10:30 local, patient attended throughout the session.")
    assert s.match == "fuzzy" and s.line_start == 2


def test_fuzzy_window_at_document_end_does_not_crash():
    text = "Individual therapy 10:00-10:30 local, patient attended throughout"
    s = DocumentIndex(text).locate("Individual therapy 10:00-10:30 local, patient atended throughout the")
    assert s.match == "fuzzy" and s.line_start == 1


# ---------------------------------------------------------------- #69 hyphenated numbers, #70 dates

def _dated_results(extra_calc=()):
    r = _results()
    r["results"][0]["calculation"] += list(extra_calc)
    r["results"][0]["params"] = {"scope": {"start": "2026-01-05", "end": "2026-01-30"}}
    r["results"][0]["facts"] = [{"kind": "encounter", "service_date": "2026-01-07"},
                                {"kind": "week", "week_start": "2026-01-26"}]
    return r


def test_postcheck_checks_numbers_joined_to_a_hyphen(tmp_path):
    conn = _pc_conn(tmp_path)
    # (10 is in the fixture's quote "line 10", so 20 is the unbacked number here.)
    assert postcheck(conn, "A 20-minute gap (T-D1 L1).", _results())["numbers_not_in_results"] == ["20"]
    assert postcheck(conn, "A 50-minute session (T-D1 L1).", _results())["ok"]
    assert postcheck(conn, "Between 30-50 minutes (T-D1 L1).", _results())["numbers_not_in_results"] == ["30"]


def test_postcheck_rejects_a_date_no_result_states(tmp_path):
    conn = _pc_conn(tmp_path)
    pc = postcheck(conn, "Seen on January 8 for 50 minutes (T-D1 L1).", _dated_results())
    assert pc["dates_not_in_results"] == ["01-08"] and not pc["ok"]
    pc = postcheck(conn, "Seen on 2026-01-09 (T-D1 L1).", _dated_results())
    assert pc["dates_not_in_results"] == ["2026-01-09"] and not pc["ok"]


def test_postcheck_accepts_dates_the_results_state(tmp_path):
    conn = _pc_conn(tmp_path)
    for text in ("Seen on January 7, 2026 for 50 minutes (T-D1 L1).",
                 "Seen on Jan 7 (T-D1 L1).",
                 "Seen on 2026-01-07 (T-D1 L1).",
                 "From January 5 to January 30 (the period asked about) (T-D1 L1).",
                 "The week of Jan 26–Feb 1 (T-D1 L1).",
                 "The week of 26 January 2026 (T-D1 L1)."):
        pc = postcheck(conn, text, _dated_results())
        assert pc["ok"], (text, pc)


def test_postcheck_reads_zero_padded_month_day_and_ignores_unidentified_contact_ids(tmp_path):
    conn = _pc_conn(tmp_path)
    assert postcheck(conn, "Week 01-26 to 02-01 (T-D1 L1).", _dated_results())["ok"]
    assert postcheck(conn, "Week 01-27 (T-D1 L1).", _dated_results())["dates_not_in_results"] == ["01-27"]
    r = _dated_results()
    assert postcheck(conn, "Contact U-2026-01-07-outreach_call-1 (T-D1 L1).", r)["ok"]
