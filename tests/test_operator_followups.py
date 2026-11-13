"""Operator, DSL and export follow-ups: compliance rejects service_types at validation (#47), the shared-label set
is computed once per plan (#57), cap notes / undated R0 rejections / export churn / timeline N+1 (#60), uncertain
encounters' minutes in row output (#65), timeline attribution with identity alternatives (#67).

Fixtures are hand-built claims (tests/helpers.py) stored in a temporary database and reconciled by the real rules;
no LLM. Patient facts here are synthetic and live only in this file. 2026-02-02 is a Monday.
"""
from __future__ import annotations

import itertools
import json
import re

import pytest
from pydantic import ValidationError

from backbone import operators
from backbone.answer import PLANNER_SYSTEM
from backbone.db import ROOT, connect
from backbone.export import build_abstraction
from backbone.query import CareStep, ComplianceStep, QueryPlan, Scope, TimelineStep, execute_plan
from backbone.reconcile import Claim, reconcile_patients

from helpers import assessment, event, with_docs

_n = itertools.count()
WEEK = dict(start="2026-02-02", end="2026-02-08")
SHARED_SQL = "SELECT doc_label FROM documents GROUP BY doc_label HAVING COUNT(*) > 1"


def _store(conn, claims: list[Claim], mrn: str = "P1"):
    """Persist claims as ingest would (documents + claims rows), then reconcile the patient."""
    conn.execute("INSERT OR IGNORE INTO patients(mrn, name, dob) VALUES (?, 'Test', '1990-01-01')", (mrn,))
    for c in with_docs(*claims):
        conn.execute("INSERT OR IGNORE INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) "
                     "VALUES (?,?,?,?,?,?)", (c.sha256, c.doc_label, json.dumps([f"docs/{c.sha256}.txt"]), "", mrn,
                                              "2026-01-01T00:00:00"))
        conn.execute("INSERT INTO claims(claim_id, sha256, doc_label, patient_mrn, kind, subject_key, evidence_type, "
                     "payload, evidence, verified) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (c.claim_id, c.sha256, c.doc_label, mrn, c.kind, c.subject_key, c.evidence_type,
                      json.dumps(c.payload), json.dumps(c.evidence), int(c.verified)))
    conn.commit()
    reconcile_patients(conn, [mrn])
    return conn


def _db(tmp_path, claims):
    return _store(connect(tmp_path / "f.db"), claims)


def _run(conn, step) -> dict:
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def _plan_claim(label="PLAN", metric="patient_present_minutes", threshold=50) -> Claim:
    sha = f"sha-{label}"
    payload = {"metric": metric, "threshold": float(threshold), "comparator": ">=", "period": "week_mon_sun",
               "counted_service_types": ["individual_therapy", "group_therapy", "family_therapy"],
               "excluded_service_types": [], "requires_patient_present": True, "effective_start": "2026-02-02",
               "effective_end": "2026-02-28", "quote": "q"}
    return Claim(f"{sha}:plan_requirement:{next(_n)}", sha, label, "plan_requirement", None, None, payload, [], True)


def _rejected_relation(label: str) -> Claim:
    """An R0-rejected claim that has no date of its own (a relation naming no encounter and no original date)."""
    sha = f"sha-{label}"
    return Claim(f"{sha}:relation:{next(_n)}", sha, label, "relation", None, None,
                 {"type": "retransmits_original", "encounter_id": None, "field": None, "old_value": None,
                  "new_value": None, "form_id": None, "original_date": None, "quote": "q"}, [], False)


# ------------------------------------------------------------------------------------------------ #47

def test_compliance_step_rejects_service_types_at_validation():
    with pytest.raises(ValidationError, match="compliance does not accept scope.service_types"):
        ComplianceStep(scope=Scope(patients=["P1"], service_types=["individual_therapy"], **WEEK))
    with pytest.raises(ValidationError, match="compliance does not accept scope.service_types"):
        QueryPlan.model_validate({"question": "t", "steps": [
            {"op": "compliance", "scope": {"patients": ["P1"], "service_types": ["group_therapy"], **WEEK}}]})
    ComplianceStep(scope=Scope(patients=["P1"], **WEEK))                  # no filter: fine
    CareStep(scope=Scope(patients=["P1"], service_types=["group_therapy"], **WEEK))   # other steps keep it


def test_planner_prompt_does_not_offer_service_types_to_compliance():
    head = PLANNER_SYSTEM.split("Operations", 1)[1].split("\n- care", 1)[0]
    assert "except compliance" in head, head          # the shared-scope sentence no longer covers compliance
    compliance_line = next(ln for ln in PLANNER_SYSTEM.splitlines() if ln.startswith("- compliance"))
    assert "service_types" in compliance_line


def test_saved_and_example_plans_still_validate():
    plans = []
    for p in sorted((ROOT / "out" / "answers").glob("*.json")):
        res = json.loads(p.read_text())
        if "plan" in res:
            plans.append((p.name, res["plan"]))
    plans += [(p.name, json.loads(p.read_text())) for p in sorted((ROOT / "plans").glob("*.json"))]
    skill = ROOT / ".claude" / "skills" / "clinical-qa"
    for md in sorted(skill.rglob("*.md")):
        plans += [(md.name, json.loads(b)) for b in re.findall(r"```json\n(.*?)```", md.read_text(), re.S)
                  if '"steps"' in b]
    assert len(plans) >= 12
    bad = []
    for name, plan in plans:
        try:
            QueryPlan.model_validate(plan)
        except ValidationError as e:
            bad.append((name, str(e)))
    assert bad == []


# ------------------------------------------------------------------------------------------------ #57

def test_shared_label_set_is_computed_once_per_plan_and_still_logged_per_step(tmp_path):
    conn = _db(tmp_path, [event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy",
                                contact=[("10:00", "10:50")])])
    executed = []
    conn.set_trace_callback(executed.append)
    sc = Scope(patients=["P1"], **WEEK)
    plan = QueryPlan(question="t", steps=[CareStep(scope=sc), TimelineStep(scope=sc, kinds=["encounters"])])
    first = execute_plan(conn, plan)
    conn.set_trace_callback(None)
    assert sum("HAVING COUNT(*) > 1" in s for s in executed) == 1, executed
    # the envelope's sql lists what each result depends on, whichever step ran the statement
    for r in first["results"]:
        assert [s["sql"] for s in r["sql"]].count(SHARED_SQL) == 1
    # re-running the same plan on the same connection gives byte-identical results (sql included)
    assert json.dumps(execute_plan(conn, plan), default=str) == json.dumps(first, default=str)


def test_shared_label_cache_does_not_outlive_its_plan(tmp_path):
    conn = _db(tmp_path, [event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy",
                                contact=[("10:00", "10:50")], sha="sha-one")])
    step = TimelineStep(scope=Scope(patients=["P1"], **WEEK), kinds=["documents"])
    assert "doc_sha" not in [f for f in _run(conn, step)["facts"] if f["kind"] == "document"][0]
    # a second document with the same label arrives on the same connection
    _store(conn, [event("NOTE-A", eid="E2", date="2026-02-04", stype="individual_therapy",
                        contact=[("11:00", "11:50")], sha="sha-two")])
    docs = [f for f in _run(conn, step)["facts"] if f["kind"] == "document"]
    assert len(docs) == 2 and all("doc_sha" in d for d in docs), docs


# ------------------------------------------------------------------------------------------------ #60

def test_cap_notes_do_not_claim_totals_for_rows_that_have_none(tmp_path, monkeypatch):
    conn = _db(tmp_path, [
        event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-B", eid="E2", date="2026-02-04", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("LOG-A", eid="E1", date="2026-02-03", stype="individual_therapy", etype="attendance_record",
              contact=[("10:00", "10:50")]),
        assessment("PHQ-A", score=12, date="2026-02-03", form_id="F1"),
        assessment("PHQ-B", score=9, date="2026-02-05", form_id="F2"),
        _rejected_relation("BAD-1"), _rejected_relation("BAD-2")])
    monkeypatch.setattr(operators, "DETAIL_LIMIT", 1)
    out = _run(conn, TimelineStep(scope=Scope(patients=["P1"], **WEEK),
                                  kinds=["encounters", "documents", "assessments"]))
    notes = {n.split(":", 1)[0]: n for n in out["notes"]}
    assert set(notes) >= {"encounters", "documents", "assessments", "rejected claims"}, out["notes"]
    assert "totals cover all rows" in notes["encounters"]          # timeline totals aggregate every encounter
    for what in ("documents", "assessments", "rejected claims"):
        assert "totals and groups cover all rows" not in notes[what] and "no totals" in notes[what], notes[what]


def test_undated_r0_rejections_are_flagged_not_placed_in_the_scope(tmp_path):
    conn = _db(tmp_path, [
        event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        _rejected_relation("BAD")])
    for sc in (Scope(patients=["P1"], start="2026-02-03", end="2026-02-03"),
               Scope(patients=["P1"], start="2026-06-01", end="2026-06-30")):
        out = _run(conn, TimelineStep(scope=sc, kinds=["encounters"]))
        r0 = [x for x in out["exclusions"] if x.get("rule") == "R0"]
        assert len(r0) == 1 and r0[0]["date"] is None
        assert r0[0].get("undated") is True, r0[0]
        assert any("no date of its own" in n for n in out["notes"]), out["notes"]
    care = _run(conn, CareStep(scope=Scope(patients=["P1"], include_excluded=True, **WEEK)))
    assert [x.get("undated") for x in care["exclusions"] if x.get("rule") == "R0"] == [True]


# ------------------------------------------------------------------------------------------------ #68

def _absent_date_observation(label: str, day: str) -> Claim:
    """An observation whose date its document never states: ingest (#52) marks it unverified and names the field in
    `unverified_absent` on the grounding entry (the last evidence entry)."""
    sha = f"sha-{label}"
    grounding = {"quote": None, "line_start": None, "line_end": None, "match": "grounding",
                 "grounding": {"date": "absent"}, "unverified_absent": ["date"]}
    return Claim(f"{sha}:observation:{next(_n)}", sha, label, "observation", None, None,
                 {"date": day, "domain": "mood", "source": "patient_report", "statement": "Mood better.",
                  "quote": "Mood better."},
                 [{"quote": "Mood better.", "line_start": 4, "line_end": 4, "match": "exact"}, grounding], False)


def test_r0_rejection_for_an_unstated_date_is_listed_undated(tmp_path):
    conn = _db(tmp_path, [
        event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        _absent_date_observation("OBS", "2026-02-03")])
    for sc in (Scope(patients=["P1"], start="2026-02-03", end="2026-02-03"),      # the inferred date
               Scope(patients=["P1"], start="2026-06-01", end="2026-06-30")):     # any other scope
        out = _run(conn, TimelineStep(scope=sc, kinds=["observations"]))
        r0 = [x for x in out["exclusions"] if x.get("rule") == "R0"]
        assert len(r0) == 1, out["exclusions"]
        assert r0[0]["date"] is None and r0[0].get("undated") is True, r0[0]
        assert "2026-02-03" not in json.dumps(r0[0]), r0[0]          # the inferred date never reaches results
        assert r0[0]["unstated_dates"] == ["date"]
    # a rejected claim whose date its document does state keeps that date
    conn2 = _store(connect(tmp_path / "g.db"), [event("NOTE-B", eid="E2", date="2026-02-04", stype="individual_therapy",
                                                      contact=[("10:00", "10:50")], verified=False)])
    out = _run(conn2, TimelineStep(scope=Scope(patients=["P1"], **WEEK), kinds=["encounters"]))
    r0 = [x for x in out["exclusions"] if x.get("rule") == "R0"]
    assert [(x["date"], x.get("undated")) for x in r0] == [("2026-02-04", None)]


def test_export_is_stable_across_an_identical_rereconcile_and_a_version_bump(tmp_path, monkeypatch):
    conn = _db(tmp_path, [event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy",
                                contact=[("10:00", "10:50")])])
    before = json.dumps(build_abstraction(conn, "P1"), default=str)
    conn.execute("UPDATE patients SET reconciled_at='2000-01-01T00:00:00' WHERE mrn='P1'")   # a later re-reconcile
    import backbone.answer as A
    monkeypatch.setattr(A, "PROMPT_VERSION", "zz-not-an-abstraction-change")
    after = json.dumps(build_abstraction(conn, "P1"), default=str)
    assert after == before


def test_timeline_fetches_document_metadata_in_one_statement(tmp_path):
    claims = [event("NOTE-A", eid=f"E{i}", date=f"2026-02-0{i}", stype="individual_therapy",
                    contact=[("10:00", "10:50")], sha="sha-roster") for i in (2, 3, 4)]
    claims += [event("NOTE-B", eid="E2", date="2026-02-02", stype="individual_therapy", etype="attendance_record",
                     contact=[("10:00", "10:50")])]
    conn = _db(tmp_path, claims)
    out = _run(conn, TimelineStep(scope=Scope(patients=["P1"], **WEEK), kinds=["documents"]))
    meta = [s for s in out["sql"] if "kind='document'" in s["sql"]]
    assert len(meta) == 1, [s["sql"] for s in meta]
    docs = {f["doc_id"]: f for f in out["facts"] if f["kind"] == "document"}
    assert sorted(docs) == ["NOTE-A", "NOTE-B"] and docs["NOTE-A"]["title"] == "NOTE-A"
    assert len(docs["NOTE-A"]["assertions"]) == 3


# ------------------------------------------------------------------------------------------------ #65 / #67

@pytest.fixture
def disputed(tmp_path):
    """E1: two equal-tier notes disagree on the service type -> a primary row and an `E1~...` alternative, both
    uncertain with 50 established minutes. E2: two equal-tier notes disagree on attendance -> uncertain, 50 min."""
    return _db(tmp_path, [
        _plan_claim(),
        event("NOTE-A", eid="E1", date="2026-02-02", stype="family_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-B", eid="E1", date="2026-02-02", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-C", eid="E2", date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-D", eid="E2", date="2026-02-03", stype="individual_therapy", disposition="no_show",
              present="no")])


def test_uncertain_encounter_minutes_are_not_shown_as_definite(disputed):
    sc = Scope(patients=["P1"], start="2026-02-03", end="2026-02-03")
    care = _run(disputed, CareStep(scope=sc, group_by="day"))
    assert care["totals"]["minutes"]["low"] == 0 and care["totals"]["minutes"]["high"] == 50
    assert "[0–50] (E2)" in care["calculation"][2], care["calculation"]
    assert care["groups"][0]["minutes_calculation"] == "[0–50] (E2)"
    fact = care["facts"][0]
    assert fact["counts_as_therapy_session"] == "uncertain"
    assert fact["patient_present_minutes"]["low"] == 50          # the contact's own measurement is unchanged
    assert fact["counted_minutes"] == {"low": 0, "high": 50}     # what it contributes to the totals
    tl = _run(disputed, TimelineStep(scope=sc, kinds=["encounters"]))
    assert "[0–50] (E2)" in tl["calculation"][0]
    comp = _run(disputed, ComplianceStep(scope=Scope(patients=["P1"], **WEEK)))
    assert "[0–50] (E2)" in comp["groups"][0]["evaluations"][0]["minutes_calculation"]


def test_definite_encounters_keep_their_row_output(tmp_path):
    conn = _db(tmp_path, [event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy",
                                contact=[("10:00", "10:50")])])
    care = _run(conn, CareStep(scope=Scope(patients=["P1"], **WEEK), group_by="day"))
    assert care["groups"][0]["minutes_calculation"] == "50 (E1)"
    assert "counted_minutes" not in care["facts"][0]


def test_timeline_attributes_shared_claims_to_the_primary_encounter(disputed):
    keys = [r[0] for r in disputed.execute("SELECT encounter_key FROM encounters WHERE encounter_id='E1' "
                                           "ORDER BY encounter_key")]
    assert keys == ["P1|E1", "P1|E1~2026-02-02-individual_therapy"]
    out = _run(disputed, TimelineStep(scope=Scope(patients=["P1"], start="2026-02-02", end="2026-02-02"),
                                      kinds=["documents"]))
    asserts = [a for f in out["facts"] if f["kind"] == "document" for a in f["assertions"]]
    assert len(asserts) == 2
    for a in asserts:
        assert a["encounter"] == "E1", a
        assert a["identity_alternatives"] == ["E1~2026-02-02-individual_therapy"], a


def test_timeline_keeps_the_alternative_when_only_it_is_in_scope(tmp_path):
    conn = _db(tmp_path, [
        event("NOTE-A", eid="E3", date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-B", eid="E3", date="2026-02-10", stype="individual_therapy", contact=[("10:00", "10:50")])])
    out = _run(conn, TimelineStep(scope=Scope(patients=["P1"], start="2026-02-10", end="2026-02-10"),
                                  kinds=["documents"]))
    asserts = [a for f in out["facts"] if f["kind"] == "document" for a in f["assertions"]]
    assert asserts and {a["encounter"] for a in asserts} == {"E3~2026-02-10-individual_therapy"}
    assert all("identity_alternatives" not in a for a in asserts)


def test_timeline_without_alternatives_is_unchanged(tmp_path):
    conn = _db(tmp_path, [event("NOTE-A", eid="E1", date="2026-02-03", stype="individual_therapy",
                                contact=[("10:00", "10:50")])])
    out = _run(conn, TimelineStep(scope=Scope(patients=["P1"], **WEEK), kinds=["documents"]))
    a = [a for f in out["facts"] if f["kind"] == "document" for a in f["assertions"]]
    assert [x["encounter"] for x in a] == ["E1"] and "identity_alternatives" not in a[0]
