"""R3 corrections and relations (#9, #10, #22, #23): hand-built claims, no LLM.

- #9  correction chains resolve the same way in any claim order; competing corrections are disputes with bounds.
- #10 contact-interval and service-type corrections are applied; corrections that cannot be applied are reported.
- #22 a retransmission/copy relation covers only the records it names, not every record of its document.
- #23 a correction that changed a number is part of the encounter's evidence and can be cited.
"""
from __future__ import annotations

import copy
import itertools
import json

from backbone.answer import postcheck
from backbone.db import connect
from backbone.operators import care, timeline
from backbone.query import CareStep, Scope, TimelineStep
from backbone.reconcile import Claim, reconcile_patient, reconcile_patients

from helpers import assessment, enc, event, relation, with_docs

GROUP = ("10:00", "11:30")
_n = itertools.count(1000)


def _run(claims):
    return reconcile_patient("P1", copy.deepcopy(claims))


def _both_orders(claims):
    """Reconcile in the given order and reversed (claims are deep-copied: reconcile annotates them in place)."""
    return _run(claims), _run(list(reversed(claims)))


def _minutes(e):
    return e["minutes_low"], e["minutes_high"], e["minutes_status"]


def _corr(label, field, old, new, eid="E1"):
    return relation(label, "corrects_field", eid=eid, field=field, old=old, new=new)


def _roster(departure="11:30", **kw):
    return event("roster", etype="attendance_record", arrival="10:00", departure=departure, scheduled=GROUP, **kw)


# ---------------------------------------------------------------- #9 chains and competing corrections

def test_chained_corrections_are_order_independent():
    claims = with_docs(
        _roster(),
        event("corrA", etype="attendance_correction", arrival="10:00", departure="11:15"),
        _corr("corrA", "departure", "11:30", "11:15"),
        _corr("corrB", "departure", "11:15", "11:00"),       # corrects the corrected value
    )
    seen = set()
    docs = [c for c in claims if c.kind == "document"]
    for order in itertools.permutations([c for c in claims if c.kind != "document"]):   # every arrival order
        res = _run(list(order) + docs)
        e = enc(res)
        assert _minutes(e) == (60, 60, "established"), e["calculation"]
        assert not res.conflicts
        # R3 decisions only: the R4 reason lists records in arrival order (cosmetic; the DB loads by claim_id)
        seen.add(json.dumps(sorted(json.dumps(d, sort_keys=True) for d in res.decisions if d["rule"] == "R3")))
    assert len(seen) == 1


def test_competing_corrections_are_disputed_with_bounds():
    claims = with_docs(
        _roster(),
        _corr("corrA", "departure", "11:30", "11:15"),
        _corr("corrB", "departure", "11:30", "11:00"),       # a different new value for the same old value
    )
    outs = []
    for res in _both_orders(claims):
        e = enc(res)
        assert _minutes(e) == (60, 75, "disputed"), e["calculation"]
        assert any(c["field"] == "correction:departure" and c["resolution"] == "disputed" for c in res.conflicts)
        assert any(d["rule"] == "R3" and d["outcome"] == "correction_disputed" for d in res.decisions)
        outs.append((e, sorted(json.dumps(d, sort_keys=True) for d in res.decisions)))
    assert outs[0] == outs[1]


def test_agreeing_corrections_are_not_a_dispute():
    claims = with_docs(_roster(), _corr("corrA", "departure", "11:30", "11:15"),
                       _corr("corrB", "departure", "11:30", "11:15"))
    for res in _both_orders(claims):
        assert _minutes(enc(res)) == (75, 75, "established")
        assert not res.conflicts


def test_correction_cycle_is_disputed():
    claims = with_docs(_roster(), _corr("corrA", "departure", "11:30", "11:15"),
                       _corr("corrB", "departure", "11:15", "11:30"))
    for res in _both_orders(claims):
        assert _minutes(enc(res)) == (75, 90, "disputed")


def test_competing_disposition_corrections_dispute_attendance():
    claims = with_docs(
        event("register", etype="attendance_record", disposition="attended", arrival="10:00", departure="11:30"),
        _corr("corrA", "disposition", "attended", "no_show"),
        _corr("corrB", "disposition", "attended", "attended_partial"),
    )
    for res in _both_orders(claims):
        assert enc(res)["attended"] == "disputed"


def test_times_compare_by_value_not_spelling():
    claims = with_docs(event("roster", etype="attendance_record", arrival="9:00", departure="10:00"),
                       _corr("corrA", "arrival", "09:00", "09:10"))
    assert _minutes(enc(_run(claims))) == (50, 50, "established")


# ---------------------------------------------------------------- #10 correction fields

def test_contact_interval_correction_changes_minutes():
    claims = with_docs(
        event("note", stype="individual_therapy", contact=[("10:00", "11:00")]),
        _corr("corr", "contact_interval", "10:00–11:00", "10:00-10:45"),
    )
    e = enc(_run(claims))
    assert _minutes(e) == (45, 45, "established"), e["calculation"]
    assert any(d["rule"] == "R3" and d["outcome"] == "field_corrected" for d in _run(claims).decisions)


def test_service_type_correction_changes_eligibility():
    claims = with_docs(
        event("note", stype="family_collateral", contact=[("10:00", "10:50")]),
        _corr("corr", "service_type", "family collateral", "Family therapy"),
    )
    e = enc(_run(claims))
    assert (e["service_type"], e["eligible"]) == ("family_therapy", "yes")
    assert _minutes(e) == (50, 50, "established")


def test_unsupported_correction_field_is_reported():
    claims = with_docs(event("note", stype="individual_therapy", contact=[("10:00", "11:00")]),
                       _corr("corr", "other", "room 4", "room 5"))
    res = _run(claims)
    e = enc(res)
    assert _minutes(e) == (60, 60, "established")
    assert any(d["rule"] == "R3" and d["outcome"] == "correction_not_applied" for d in res.decisions)
    assert any("correction" in f and "not applied" in f for f in e["flags"])


def test_unparseable_and_unmatched_corrections_are_reported():
    for corr in (_corr("corr", "contact_interval", "the morning slot", "10:00-10:45"),   # unparseable
                 _corr("corr", "departure", "12:00", "11:00"),                         # matches no record
                 _corr("corr", "service_type", "group_therapy", "yoga")):              # not a service type
        res = _run(with_docs(_roster(), corr))
        assert any(d["outcome"] == "correction_not_applied" for d in res.decisions), corr.payload
        assert any("not applied" in f for f in enc(res)["flags"]), corr.payload


def test_correction_without_encounter_id_is_reported():
    res = _run(with_docs(_roster(), relation("corr", "corrects_field", field="departure", old="11:30", new="11:15")))
    assert _minutes(enc(res)) == (90, 90, "established")
    assert any(d["outcome"] == "correction_not_applied" for d in res.decisions)


# ---------------------------------------------------------------- #22 copy relations are scoped

def test_mixed_retransmission_document_still_counts_its_new_record():
    claims = with_docs(
        _roster(departure="11:30"),
        # one document: a resent roster for E1 plus a new, signed note for E2
        event("mixed", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("mixed", "retransmits_original", eid="E1"),
        event("mixed", eid="E2", date="2026-02-03", stype="individual_therapy", contact=[("09:00", "09:50")]),
    )
    res = _run(claims)
    e2 = enc(res, "E2")
    assert (e2["eligible"], *_minutes(e2)) == ("yes", 50, 50, "established")
    resent = [d for d in res.decisions if d["outcome"] == "evidence_excluded" and d["rule"] == "R3"]
    assert [d["subject_key"] for d in resent] == ["P1|E1"]


def test_mixed_retransmission_keeps_a_new_id_less_record_of_the_same_day():
    claims = with_docs(
        _roster(),
        event("mixed", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("mixed", "retransmits_original", eid="E1"),
        # same document and date, no encounter ID, a different service: R1 files it as its own contact
        event("mixed", eid=None, stype="individual_therapy", contact=[("11:30", "12:15")]),
    )
    res = _run(claims)
    new = next(e for e in res.encounters if e["service_type"] == "individual_therapy")
    assert new["encounter_key"].startswith("P1|U-")
    assert (new["eligible"], *_minutes(new)) == ("yes", 45, 45, "established")


def test_retransmission_without_encounter_id_still_covers_the_whole_document():
    claims = with_docs(
        _roster(),
        event("resent", etype="attendance_record", disposition="no_show", present="no"),
        relation("resent", "retransmits_original"),
    )
    e = enc(_run(claims))
    assert e["attended"] == "yes"          # the resent record carries no weight


def test_mixed_copy_document_keeps_its_new_assessment():
    new = assessment("import", score=10, date="2026-01-23")             # newly completed, not a copy
    claims = with_docs(
        assessment("portal", score=14, date="2026-01-16", form_id="F1"),
        assessment("import", score=14, date="2026-01-16", form_id="F1"),
        relation("import", "copies_measurement", form_id="F1"),
        new,
        assessment("clinic", score=12, date="2026-01-23"),             # another record of the Jan 23 PHQ-9
    )
    res = _run(claims)
    by_date = {a["completed_date"]: a for a in res.assessments}
    assert by_date["2026-01-16"]["copy_claim_ids"] and len(by_date["2026-01-16"]["claim_ids"]) == 1
    jan23 = by_date["2026-01-23"]
    assert jan23["copy_claim_ids"] == [] and new.claim_id in jan23["claim_ids"] and jan23["status"] == "disputed"
    assert not any(d["outcome"] == "copy_not_distinct" and "2026-01-23" in d["subject_key"] for d in res.decisions)


def test_copy_relation_with_form_id_covers_unlabelled_copy_of_that_date():
    a = assessment("import", score=14, date="2026-01-16")
    claims = with_docs(assessment("portal", score=14, date="2026-01-16", form_id="F1"), a,
                       relation("import", "copies_measurement", form_id="F1"))
    claims[2].payload["original_date"] = "2026-01-16"
    res = _run(claims)
    assert [x["copy_claim_ids"] for x in res.assessments] == [[a.claim_id]]


# ---------------------------------------------------------------- #23 evidence for relation-only corrections

ROSTER_TEXT = "Roster R-1\nEncounter E1 2026-02-02 group\nPatient arrival 10:00, departure 11:00, attended\n"
CORR_TEXT = "Correction C-1\nCorrection: departure for E1 is 10:45, replacing 11:00.\n"


def _db_claim(sha, label, kind, i, payload, quote, line, etype=None, subject=None):
    return Claim(f"{sha[:12]}:{kind}:{i}", sha, label, kind, subject, etype, payload,
                 [{"quote": quote, "line_start": line, "line_end": line, "match": "exact"}] if quote else [], True)


def _correction_db(tmp_path):
    conn = connect(tmp_path / "corr.db")
    ra, rc = "a" * 64, "c" * 64
    for sha, label, text in ((ra, "R-1", ROSTER_TEXT), (rc, "C-1", CORR_TEXT)):
        conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) "
                     "VALUES (?,?,?,?,?,?)", (sha, label, json.dumps([f"documents/{label}.txt"]), text, "P1",
                                              "2026-01-01T00:00:00"))
    conn.execute("INSERT INTO patients(mrn) VALUES ('P1')")
    ev = event("R-1", etype="attendance_record", arrival="10:00", departure="11:00", stype="group_therapy")
    claims = [
        _db_claim(ra, "R-1", "document", 0, {"signed": True, "finality": "final", "signed_at": None}, None, None,
                  subject="R-1"),
        _db_claim(ra, "R-1", "service_event", 0, ev.payload, "Patient arrival 10:00, departure 11:00, attended", 3,
                  etype="attendance_record", subject="E1"),
        _db_claim(rc, "C-1", "document", 0, {"signed": True, "finality": "final", "signed_at": None}, None, None,
                  subject="C-1"),
        _db_claim(rc, "C-1", "relation", 0, {"type": "corrects_field", "encounter_id": "E1", "field": "departure",
                                             "old_value": "11:00", "new_value": "10:45", "form_id": None,
                                             "original_date": None, "quote": "q"},
                  "Correction: departure for E1 is 10:45, replacing 11:00.", 2, subject="E1"),
    ]
    for c in claims:
        conn.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (c.claim_id, c.sha256, c.doc_label, "P1", c.kind, c.subject_key, c.evidence_type,
                      json.dumps(c.payload), json.dumps(c.evidence), 1))
    conn.commit()
    reconcile_patients(conn, ["P1"])
    return conn


SCOPE = dict(patients=["P1"], start="2026-02-02", end="2026-02-02")


def test_relation_only_correction_is_in_care_evidence_and_citable(tmp_path):
    conn = _correction_db(tmp_path)
    env = care(conn, CareStep(scope=Scope(**SCOPE)))
    assert env["totals"]["minutes"] == {"low": 45, "high": 45, "status": "established"}
    assert "C-1" in {x["doc_id"] for x in env["evidence"]}
    results = {"question": "q", "plan": {"question": "q", "steps": []}, "results": [env]}
    pc = postcheck(conn, "45 minutes: departure corrected to 10:45 (C-1 L2; R-1 L3).", results)
    assert pc["ok"], pc


def test_relation_only_correction_document_in_timeline_has_no_fake_assertion(tmp_path):
    conn = _correction_db(tmp_path)
    env = timeline(conn, TimelineStep(scope=Scope(**SCOPE), kinds=["encounters", "documents"]))
    docs = {f["doc_id"]: f for f in env["facts"] if f["kind"] == "document"}
    assert docs["C-1"]["assertions"] == []
    assert docs["C-1"]["relations"][0]["type"] == "corrects_field"
    assert len(docs["R-1"]["assertions"]) == 1


def test_correction_already_cited_by_its_own_document_is_not_added_again():
    span = [{"quote": "Correction: departure 11:15", "line_start": 7, "line_end": 7, "match": "exact"}]
    ev = event("corrA", etype="attendance_correction", arrival="10:00", departure="11:15")
    rel = _corr("corrA", "departure", "11:30", "11:15")
    ev.evidence, rel.evidence = span, span
    e = enc(_run(with_docs(_roster(), ev, rel)))
    assert rel.claim_id not in e["claim_ids"] and ev.claim_id in e["claim_ids"]
    rel_only = _corr("corrB", "departure", "11:30", "11:15")
    rel_only.evidence = span
    e = enc(_run(with_docs(_roster(), rel_only)))
    assert rel_only.claim_id in e["claim_ids"]
