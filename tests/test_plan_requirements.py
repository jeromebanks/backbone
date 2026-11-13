"""Treatment-plan requirements and weekly compliance on hand-built claims (no LLM, no source documents).

Each test reproduces one reported issue (#6, #7, #8, #18, #19, #21, #38). Weeks are Mon–Sun; 2026-02-02 is a Monday.
"""
import itertools

import pytest

from backbone.db import connect
from backbone.project import evaluate_requirement
from backbone.query import ComplianceStep, QueryPlan, Scope, execute_plan
from backbone.reconcile import Claim, persist, reconcile_patient

from helpers import doc, event, with_docs

ALL_THERAPY = ["individual_therapy", "group_therapy", "family_therapy"]
WEEK = dict(start="2026-02-02", end="2026-02-08")
_n = itertools.count()


def plan(label, metric, threshold, *, comparator=">=", period="week_mon_sun", counted=ALL_THERAPY, excluded=(),
         present=True, start="2026-02-02", end="2026-02-28", sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    i = next(_n)
    payload = {"metric": metric, "threshold": float(threshold), "comparator": comparator, "period": period,
               "counted_service_types": list(counted), "excluded_service_types": list(excluded),
               "requires_patient_present": present, "effective_start": start, "effective_end": end, "quote": "q"}
    return Claim(f"{sha}:plan_requirement:{i}", sha, label, "plan_requirement", None, None, payload, [], True)


def session(eid, day, stype, start, end, **kw) -> Claim:
    return event(f"note-{eid}", eid=eid, date=day, stype=stype, contact=[(start, end)], **kw)


def build(tmp_path, claims):
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('P1', 'Test', '1990-01-01')")
    res = reconcile_patient("P1", claims)
    with conn:
        persist(conn, res)
    return conn, res


def compliance(conn, **scope):
    step = ComplianceStep(scope=Scope(patients=["P1"], include_evidence=False, **{**WEEK, **scope}))
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def week(conn):
    groups = compliance(conn)["groups"]
    assert len(groups) == 1
    return groups[0]


# ---------------------------------------------------------------- #6 each requirement counts its own service types

def test_each_requirement_is_evaluated_on_its_own_service_types(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2, counted=["individual_therapy"]),
        plan("PLAN", "patient_present_minutes", 60),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "group_therapy", "10:00", "11:00"),
    ))
    w = week(conn)
    reqs = {r["metric"]: r for r in w["evaluations"][0]["requirements"]}
    assert reqs["sessions"]["value"]["low"] == 1          # the group session does not count for an individual goal
    assert reqs["sessions"]["status"] == "NOT_MET"
    assert reqs["sessions"]["counted_service_types"] == ["individual_therapy"]
    assert reqs["patient_present_minutes"]["status"] == "MET"           # 50 + 60 across all therapy
    assert w["status"] == "NOT_MET"


# ---------------------------------------------------------------- #7 period, excluded types, presence

def test_non_weekly_period_is_not_judged_on_a_week(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 4, period="month"),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
    ))
    w = week(conn)
    r = w["evaluations"][0]["requirements"][0]
    assert r["status"] == "UNDETERMINED" and "period" in r["reason"]
    assert w["status"] == "UNDETERMINED"


def test_excluded_service_types_are_not_counted(tmp_path):
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "therapy_days", 2, counted=[], excluded=["family_therapy"]),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "family_therapy", "13:00", "13:50"),
    ))
    assert res.plans[0]["counted_types"] == ["group_therapy", "individual_therapy"]
    w = week(conn)
    assert w["evaluations"][0]["requirements"][0]["value"]["low"] == 1
    assert w["status"] == "NOT_MET"


def test_patient_presence_requirement_uses_present_sessions(tmp_path):
    # requires_patient_present=True is what R5 eligibility already enforces: the partner-only session never counts
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2, present=True),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "family_therapy", "13:00", "13:50", present="no"),
    ))
    assert week(conn)["status"] == "NOT_MET"


def test_presence_not_required_is_a_lower_bound(tmp_path):
    # the projection only counts patient-present therapy, so for a goal that does not require presence the
    # count is a lower bound: 1 present session cannot show that "at least 2 sessions" was missed
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2, present=False),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "family_therapy", "13:00", "13:50", present="no"),
    ))
    r = week(conn)["evaluations"][0]["requirements"][0]
    assert r["status"] == "UNDETERMINED" and r["value"]["low"] == 1 and r["value"]["high"] is None


def test_non_therapy_counted_types_are_a_lower_bound(tmp_path):
    # eligibility (R5) only counts psychotherapy, so a goal over medication management cannot be shown NOT_MET
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        session("E1", "2026-02-02", "medication_management", "09:00", "09:20"),
    ))
    r = week(conn)["evaluations"][0]["requirements"][0]
    assert r["status"] == "UNDETERMINED" and "lower bound" in r["reason"]


def test_requirement_with_every_type_excluded_is_undetermined(tmp_path):
    # an empty type list must not fall through to "no type filter" (which would count everything)
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=[], excluded=ALL_THERAPY),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
    ))
    assert any(d["outcome"] == "no_counted_types" for d in res.decisions)
    w = week(conn)
    assert w["status"] == "UNDETERMINED" and w["evaluations"][0]["encounters"] == []


# ---------------------------------------------------------------- #8 draft plans are not operative

def _revision_week(tmp_path, *, finality):
    claims = with_docs(
        plan("PLAN", "therapy_days", 2),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
    )
    claims += [plan("REV", "therapy_days", 1, start="2026-02-04"),
               doc("REV", finality=finality, signed=finality == "final")]
    return build(tmp_path, claims)


def test_draft_revision_does_not_supersede_signed_plan(tmp_path):
    conn, res = _revision_week(tmp_path, finality="draft")
    assert [p["doc_label"] for p in res.plans] == ["PLAN"]
    assert any(d["rule"] == "R2" and d["outcome"] == "plan_not_operative" for d in res.decisions)
    assert week(conn)["status"] == "NOT_MET"                     # 1 day vs >= 2, the draft's >= 1 is ignored


def test_signed_revision_supersedes(tmp_path):
    conn, _ = _revision_week(tmp_path, finality="final")
    assert week(conn)["status"] == "UNDETERMINED"                # 1 day: misses >= 2, meets >= 1 (R9)


# ---------------------------------------------------------------- #18 equality against bounds

@pytest.mark.parametrize("low,high,expected", [
    (1, 3, "UNDETERMINED"),        # 2 is possible inside the bounds
    (2, 2, "MET"),
    (3, 5, "NOT_MET"),
    (0, 1, "NOT_MET"),
    (0, None, "UNDETERMINED"),     # unbounded high
])
def test_equality_requirement_against_bounds(low, high, expected):
    req = {"requirement_key": "k", "metric": "sessions", "comparator": "==", "threshold": 2}
    totals = {"sessions": {"low": low, "high": high}}
    assert evaluate_requirement(req, totals)["status"] == expected


# ---------------------------------------------------------------- #19 / #38 requirement identity

def test_same_metric_requirements_in_one_plan_both_persist_and_both_apply(tmp_path):
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2, counted=["individual_therapy"]),
        plan("PLAN", "sessions", 1, counted=["group_therapy"]),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-04", "individual_therapy", "09:00", "09:50"),
        session("E3", "2026-02-03", "group_therapy", "10:00", "11:00"),
    ))
    assert len({p["requirement_key"] for p in res.plans}) == 2
    w = week(conn)
    assert len(w["evaluations"]) == 1                            # one plan: co-requirements, not alternatives
    assert sorted(r["value"]["low"] for r in w["evaluations"][0]["requirements"]) == [1, 2]
    assert w["status"] == "MET"
    assert not any("conflicting" in n for n in w["notes"])


def test_same_label_documents_with_different_requirements_both_survive(tmp_path):
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "therapy_days", 2, sha="sha-a"),
        plan("PLAN", "therapy_days", 1, sha="sha-b"),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
    ))
    assert len({p["requirement_key"] for p in res.plans}) == 2
    w = week(conn)
    assert w["status"] == "UNDETERMINED"                         # two documents disagree; neither silently wins
    assert any("conflicting requirements" in n for n in w["notes"])


def test_identical_plan_restated_by_another_document_counts_once_with_a_decision(tmp_path):
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "therapy_days", 2, sha="sha-a"),
        plan("PLAN", "therapy_days", 2, sha="sha-b"),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
    ))
    assert len(res.plans) == 2                                   # both documents stay traceable
    assert [d["outcome"] for d in res.decisions if d["rule"] == "R3"] == ["plan_restated"]
    w = week(conn)
    assert w["status"] == "NOT_MET" and len(w["evaluations"]) == 1
    assert not any("conflicting" in n for n in w["notes"])


def test_same_label_observations_from_different_documents_both_survive():
    def obs(sha, quote):
        return Claim(f"{sha}:observation:{next(_n)}", sha, "NOTE", "observation", None, None,
                     {"date": "2026-02-02", "domain": "mood", "source": "patient_report", "statement": quote,
                      "quote": quote}, [], True)
    res = reconcile_patient("P1", with_docs(obs("sha-a", "Mood is better."), obs("sha-b", "Mood is worse."),
                                            obs("sha-c", "Mood is better.")))
    assert sorted(o["statement"] for o in res.observations) == ["Mood is better.", "Mood is worse."]
    merged = next(o for o in res.observations if o["statement"] == "Mood is better.")
    assert len(merged["claim_ids"]) == 2                        # identical statement: one observation, both sources


# ---------------------------------------------------------------- #21 compliance and a service-type scope

def test_compliance_does_not_silently_ignore_a_service_type_scope(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "group_therapy", "10:00", "11:00"),
    ))
    # ComplianceStep rejects service_types at validation (#47); the operator's own guard covers unvalidated steps
    step = ComplianceStep.model_construct(op="compliance", consecutive_below=None, scope=Scope(
        patients=["P1"], include_evidence=False, service_types=["individual_therapy"], **WEEK))
    r = execute_plan(conn, QueryPlan.model_construct(question="t", steps=[step], unsupported_reason=None))["results"][0]
    assert r["groups"] == [] and r["totals"].get("unsupported")
    assert any("service_types" in n for n in r["notes"])
