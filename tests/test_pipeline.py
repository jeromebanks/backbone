"""End-to-end tests on the supplied documents, using the committed extraction cache (zero LLM calls).

The golden values below were derived by hand from the source documents (see README "Expected results");
they live only in tests, never in production code.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backbone import ingest as ingest_mod
from backbone.db import ROOT, connect, connect_readonly
from backbone.extract import CACHE_DIR, extract_document
from backbone.ingest import ingest, sha256_bytes
from backbone.query import CareStep, CompareStep, ComplianceStep, QueryPlan, Scope, TimelineStep, execute_plan
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, ServiceEvent

DOCS = ROOT / "documents"
MRN = "HG-M042"
PERIOD = dict(start="2026-01-05", end="2026-01-30")

pytestmark = pytest.mark.skipif(not any(CACHE_DIR.glob("*.json")), reason="extraction cache not built")


def _no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called")
    monkeypatch.setattr("backbone.extract.complete_json", boom)


def build(tmp_path, monkeypatch, *paths) -> tuple:
    _no_llm(monkeypatch)
    conn = connect(tmp_path / "t.db")
    stats = ingest(conn, list(paths) or [DOCS], log=lambda *a: None)
    reconcile_patients(conn, stats["affected_patients"])
    return conn, stats


def care(conn, **kw):
    step = CareStep(scope=Scope(patients=[MRN], include_evidence=False, **{**PERIOD, **kw}), group_by="week")
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def weeks(conn):
    step = ComplianceStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), consecutive_below=2)
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn, stats = build(tmp_path, monkeypatch)
    return conn, stats


def test_rebuild_from_cache_uses_no_llm(db):
    _, stats = db
    assert stats["extracted_llm"] == 0 and stats["extracted_cache"] == 31 and not stats["failed"]


def test_golden_totals(db):
    t = care(db[0])["totals"]
    assert (t["sessions"]["low"], t["sessions"]["high"]) == (12, 12)
    assert (t["therapy_days"]["low"], t["therapy_days"]["high"]) == (11, 11)
    assert (t["minutes"]["low"], t["minutes"]["high"]) == (585, 595)
    by = {x["service_type"]: x["sessions"]["low"] for x in t["by_service_type"]}
    assert by == {"individual_therapy": 5, "group_therapy": 5, "family_therapy": 2}


def test_golden_weeks(db):
    r = weeks(db[0])
    got = {w["week_start"]: (w["status"], w["evaluations"][0]["totals"]["therapy_days"]["low"],
                             w["evaluations"][0]["totals"]["minutes"]["low"], w["evaluations"][0]["totals"]["minutes"]["high"])
           for w in r["groups"]}
    assert got == {
        "2026-01-05": ("NOT_MET", 3, 140, 140),
        "2026-01-12": ("NOT_MET", 2, 120, 120),
        "2026-01-19": ("MET", 3, 180, 180),
        "2026-01-26": ("UNDETERMINED", 3, 145, 155),
    }
    assert r["facts"][0]["status"] == "yes"            # two consecutive weeks below goal (W1, W2)


def test_golden_days_19_and_21(db):
    conn = db[0]
    for day, sessions, minutes in (("2026-01-19", 2, 90), ("2026-01-21", 1, 45)):
        t = care(conn, start=day, end=day)["totals"]
        assert (t["sessions"]["low"], t["minutes"]["low"], t["minutes"]["high"]) == (sessions, minutes, minutes)


def test_golden_assessments(db):
    step = TimelineStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), kinds=["assessments"])
    facts = execute_plan(db[0], QueryPlan(question="t", steps=[step]))["results"][0]["facts"]
    assert [(f["date"], f["total_score"]) for f in facts] == [("2026-01-05", 18), ("2026-01-16", 14), ("2026-01-30", 10)]
    assert next(f for f in facts if f["date"] == "2026-01-16")["copies_not_counted"] == ["BH-D014"]


def test_every_evidence_passage_is_real(db):
    conn = db[0]
    for r in conn.execute("SELECT c.evidence, d.text FROM claims c JOIN documents d USING(sha256)"):
        lines = r["text"].splitlines()
        for s in json.loads(r["evidence"]):
            if s["line_start"]:
                assert 1 <= s["line_start"] <= s["line_end"] <= len(lines)


def test_duplicate_file_does_not_change_results(tmp_path, monkeypatch):
    d = tmp_path / "docs"
    shutil.copytree(DOCS, d)
    shutil.copy(d / "BH-D105_individual_2026-01-19.txt", d / "copy_of_D105.txt")
    conn, stats = build(tmp_path, monkeypatch, d)
    assert stats["duplicate_files"] == 1 and stats["new_documents"] == 31
    assert care(conn)["totals"]["sessions"]["low"] == 12


def test_near_duplicate_document_is_absorbed(db, tmp_path, monkeypatch):
    """A renamed, re-whitespaced copy has a different hash, so it is extracted as a new document; encounter-level
    reconciliation must still not double count. The 'LLM' here replays the original document's extraction."""
    conn = db[0]
    src = DOCS / "BH-D110_individual_primary_record_2026-01-26.txt"
    orig_sha = sha256_bytes(src.read_bytes())
    nd = tmp_path / "rescan_of_HG-E115.txt"
    nd.write_text("\n\n" + src.read_text().replace(". ", ".  ") + "\n")

    def replay(sha, filename, text, **kw):
        return extract_document(orig_sha, filename, text)
    monkeypatch.setattr(ingest_mod, "extract_document", replay)
    before = care(conn)["totals"]
    stats = ingest(conn, [nd], log=lambda *a: None)
    reconcile_patients(conn, stats["affected_patients"])
    assert stats["new_documents"] == 1
    after = care(conn)["totals"]
    assert (after["sessions"], after["minutes"]) == (before["sessions"], before["minutes"])


def test_second_patient_is_isolated(db, tmp_path, monkeypatch):
    conn = db[0]
    before = json.dumps(care(conn)["totals"], sort_keys=True)
    f = tmp_path / "other_patient.txt"
    f.write_text("Patient: Alex Doe | MRN ZZ-1\nIndividual therapy 2026-01-07 10:00-10:50, completed.\n")
    ex = Extraction(
        document=DocumentInfo(document_id=None, title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name="Alex Doe", patient_mrn="ZZ-1", patient_dob=None,
                              relations=[]),
        service_events=[ServiceEvent(
            encounter_id="X1", related_encounter_id=None, appointment_id=None, service_date="2026-01-07",
            service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
            disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
            patient_departure=None, patient_contact_intervals=[{"start": "10:00", "end": "10:50"}],
            nontherapeutic_intervals=[], stated_minutes=None, clinicians=[],
            quotes=["Individual therapy 2026-01-07 10:00-10:50, completed."])],
        assessments=[], observations=[], plan_requirements=[])
    monkeypatch.setattr(ingest_mod, "extract_document", lambda *a, **k: (ex, {"from_cache": False}))
    stats = ingest(conn, [f], log=lambda *a: None)
    assert stats["affected_patients"] == ["ZZ-1"]
    reconcile_patients(conn, stats["affected_patients"])
    assert json.dumps(care(conn)["totals"], sort_keys=True) == before
    all_care = execute_plan(conn, QueryPlan(question="t", steps=[CareStep(
        scope=Scope(patients="all", include_evidence=False, **PERIOD), group_by="patient")]))["results"][0]
    assert {g["group"]: g["minutes"]["low"] for g in all_care["groups"]} == {"HG-M042": 585, "ZZ-1": 50}


def test_restart_new_process_reuses_abstraction(db, tmp_path):
    out = subprocess.run([sys.executable, "-m", "backbone", "--db", str(tmp_path / "t.db"), "plan",
                          str(ROOT / "plans" / "weekly_compliance.json")], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert '"UNDETERMINED"' in out.stdout and '"low": 585' in out.stdout


def test_corpus_has_no_quarantined_documents(db):
    stats = db[1]
    assert stats["quarantined"] == [] and stats["affected_patients"] == [MRN]


def test_reingest_is_noop(db, monkeypatch):
    conn = db[0]
    stats = ingest(conn, [DOCS], log=lambda *a: None)
    assert stats["new_documents"] == 0 and stats["already_ingested"] == 31 and stats["affected_patients"] == []


def test_query_results_are_deterministic(db):
    conn = db[0]
    plan = QueryPlan.model_validate_json((ROOT / "plans" / "weekly_compliance.json").read_text())
    a = json.dumps(execute_plan(conn, plan), sort_keys=True, default=str)
    b = json.dumps(execute_plan(connect_readonly(Path(conn.execute("PRAGMA database_list").fetchone()[2])), plan),
                   sort_keys=True, default=str)
    assert a == b


def test_invalid_plans_are_rejected():
    with pytest.raises(Exception):
        QueryPlan.model_validate({"question": "q", "steps": [{"op": "sql", "query": "DROP TABLE x"}]})
    with pytest.raises(Exception):
        Scope(patients=["X"], start="2026-02-01", end="2026-01-01")


def test_fluent_dsl_builds_the_same_plan(db):
    from backbone.dsl import care as q
    conn = db[0]
    fluent = (q.for_patient(MRN).during(PERIOD["start"], PERIOD["end"]).without_evidence()
               .care(group_by="week").compliance(consecutive_below=2))
    json_plan = QueryPlan(question="(python DSL)", steps=[
        CareStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), group_by="week"),
        ComplianceStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), consecutive_below=2)])
    assert fluent.plan() == json_plan
    assert json.dumps(fluent.execute(conn), default=str) == json.dumps(execute_plan(conn, json_plan), default=str)
    assert "SELECT" in fluent.to_sql(conn)


# ---------------------------------------------------------------- treatment-plan revisions (R9), no LLM

def _add_req(conn, doc, metric, thr, start, end="2026-01-30"):
    conn.execute("INSERT INTO plan_requirements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (f"{MRN}|plan|{doc}|{metric}|{start}", MRN, doc, metric, ">=", thr, "week_mon_sun",
                  json.dumps(["family_therapy", "group_therapy", "individual_therapy"]), 1, start, end, None, "[]"))
    conn.commit()


def _week_status(conn):
    return {w["week_start"]: w["status"] for w in weeks(conn)["groups"]}


def test_midweek_revision_judges_whole_week_against_each_plan(db):
    conn = db[0]
    # revision effective Wednesday Jan 21: >= 2 days and >= 120 minutes
    _add_req(conn, "REV-1", "therapy_days", 2, "2026-01-21")
    _add_req(conn, "REV-1", "patient_present_minutes", 120, "2026-01-21")
    st = _week_status(conn)
    # W3 (Jan 19-25): whole week 3 days / 180 min meets the original AND the revision -> MET
    # (judging the Jan 19-20 segment alone against a weekly goal would wrongly give NOT_MET)
    assert st["2026-01-19"] == "MET"
    # W4 is entirely under the revision: 145-155 min >= 120 -> MET (no longer undetermined)
    assert st["2026-01-26"] == "MET"
    assert st["2026-01-05"] == st["2026-01-12"] == "NOT_MET"
    step = CompareStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), split="plan_change")
    r = execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]
    assert "split at plan change effective 2026-01-21" in r["notes"][0]
    assert [g["side"] for g in r["groups"]] == ["before", "after"]


def test_restated_identical_goal_is_not_a_change(db):
    conn = db[0]
    _add_req(conn, "COPY-PLAN", "therapy_days", 3, "2026-01-05")
    _add_req(conn, "COPY-PLAN", "patient_present_minutes", 150, "2026-01-05")
    assert _week_status(conn) == {"2026-01-05": "NOT_MET", "2026-01-12": "NOT_MET", "2026-01-19": "MET",
                                  "2026-01-26": "UNDETERMINED"}
    step = CompareStep(scope=Scope(patients=[MRN], include_evidence=False, **PERIOD), split="plan_change")
    r = execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]
    assert r["groups"] == [] and "no treatment-plan change" in r["notes"][0]


def test_conflicting_same_start_goals_become_undetermined(db):
    conn = db[0]
    _add_req(conn, "OTHER-PLAN", "patient_present_minutes", 200, "2026-01-05")
    w = {x["week_start"]: x for x in weeks(conn)["groups"]}
    assert w["2026-01-19"]["status"] == "UNDETERMINED"          # 180: meets 150, misses 200
    assert any("conflicting requirements" in n for n in w["2026-01-19"]["notes"])
    assert w["2026-01-05"]["status"] == "NOT_MET"                # 140 misses both


# ---------------------------------------------------------------- agent-facing CLI helpers (used by the clinical-qa skill)

def test_plan_summary_and_postcheck_cli(db, tmp_path):
    dbp = str(tmp_path / "t.db")
    plan_obj = json.loads((ROOT / "plans" / "weekly_compliance.json").read_text())
    for st in plan_obj["steps"]:
        st["scope"]["include_evidence"] = True          # citations must be backed by evidence in the results
    plan = json.dumps(plan_obj)
    out = subprocess.run([sys.executable, "-m", "backbone", "--db", dbp, "plan", "-", "--summary",
                          "--out", str(tmp_path / "r.json")], input=plan, capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "WEEK 2026-01-26 [UNDETERMINED]" in out.stdout and "CONFLICT HG-E115" in out.stdout
    good = tmp_path / "good.md"
    good.write_text("Week of Jan 26: 145–155 minutes, UNDETERMINED (BH-D110 L7; BH-D111 L7).")
    bad = tmp_path / "bad.md"
    bad.write_text("Week of Jan 26: 162 minutes (BH-D110 L99).")
    run = lambda f: subprocess.run([sys.executable, "-m", "backbone", "--db", dbp, "postcheck", str(f), "--results",
                                    str(tmp_path / "r.json")], capture_output=True, text=True, cwd=ROOT)
    assert run(good).returncode == 0
    r = run(bad)
    assert r.returncode == 1 and "162" in r.stdout and "BH-D110 L99" in r.stdout


def test_invalid_plan_cli_fails_loudly(db, tmp_path):
    out = subprocess.run([sys.executable, "-m", "backbone", "--db", str(tmp_path / "t.db"), "plan", "-", "--summary"],
                         input='{"question":"x","steps":[{"op":"sql","q":"DROP TABLE claims"}]}',
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 2 and "INVALID PLAN" in out.stderr


def test_skill_example_plans_stay_valid(db):
    """Every QueryPlan example shipped in the clinical-qa skill must validate and execute."""
    import re
    txt = (ROOT / ".claude" / "skills" / "clinical-qa" / "reference" / "plan-examples.md").read_text()
    blocks = re.findall(r"```json\n(.*?)```", txt, re.S)
    assert len(blocks) >= 8
    for b in blocks:
        res = execute_plan(db[0], QueryPlan.model_validate_json(b))
        assert res["results"]
