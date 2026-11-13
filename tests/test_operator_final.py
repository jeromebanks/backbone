"""Operator output follow-ups: minute expressions of identity alternatives (#73) and goal-counted
non-psychotherapy visits in compliance output (#79).

Hand-built claims (tests/helpers.py), reconciled by the real rules into a temporary database; no LLM. Patient facts
here are synthetic and live only in this file. 2026-02-02 is a Monday.
"""
from __future__ import annotations

import itertools
import re

from backbone.db import connect
from backbone import project
from backbone.query import CareStep, CompareStep, ComplianceStep, QueryPlan, Scope, TimelineStep, execute_plan
from backbone.reconcile import Claim, persist, reconcile_patient

from helpers import event, with_docs

ALL_THERAPY = ["individual_therapy", "group_therapy", "family_therapy"]
ALL_THERAPY_SORTED = sorted(ALL_THERAPY)
WEEK = dict(start="2026-02-02", end="2026-02-08")
_n = itertools.count(9000)


def plan(label, metric, threshold, *, counted=ALL_THERAPY, start="2026-02-02") -> Claim:
    sha = f"sha-{label}"
    payload = {"metric": metric, "threshold": float(threshold), "comparator": ">=", "period": "week_mon_sun",
               "counted_service_types": list(counted), "excluded_service_types": [],
               "requires_patient_present": True, "effective_start": start, "effective_end": "2026-02-28",
               "quote": "q"}
    return Claim(f"{sha}:plan_requirement:{next(_n)}", sha, label, "plan_requirement", None, None, payload, [], True)


def build(tmp_path, claims):
    conn = connect(tmp_path / "t.db")
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('P1', 'Test', '1990-01-01')")
    res = reconcile_patient("P1", with_docs(*claims))
    with conn:
        persist(conn, res)
    return conn, res


def run(conn, step) -> dict:
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def scope(**kw):
    return Scope(patients=["P1"], include_evidence=False, **{**WEEK, **kw})


# ---------------------------------------------------------------- #73 identity alternatives count once

def _disputed_type(tmp_path, eid="E1"):
    """Two equal-tier notes disagree on the service type: a primary row and a `~` alternative, both uncertain."""
    return build(tmp_path, [
        plan("PLAN", "patient_present_minutes", 50),
        event("NOTE-A", eid=eid, date="2026-02-03", stype="family_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-B", eid=eid, date="2026-02-03", stype="individual_therapy", contact=[("10:00", "10:50")]),
        event("NOTE-C", eid="E2", date="2026-02-04", stype="individual_therapy", contact=[("10:00", "10:30")])])


def _value(expr: str) -> tuple[float, float]:
    """Evaluate a minutes expression: `a + b`, `[lo–hi] (key)`, `max(x, y)`; returns (low, high)."""
    expr = re.sub(r" \([^()]*\)", "", expr)                      # drop the "(key)" labels
    lo = eval(re.sub(r"\[(\d+)–(\d+|\?)\]", r"\1", expr))
    hi = eval(re.sub(r"\[(\d+)–(\d+|\?)\]", lambda m: m[2] if m[2] != "?" else "float('inf')", expr))
    return lo, hi


def test_care_minutes_expression_of_identity_alternatives_produces_the_total(tmp_path):
    conn, res = _disputed_type(tmp_path)
    keys = sorted(e["encounter_key"] for e in res.encounters if e["encounter_id"] == "E1")
    assert keys == ["P1|E1", "P1|E1~2026-02-03-individual_therapy"], keys
    out = run(conn, CareStep(scope=scope(), group_by="day"))
    assert (out["totals"]["minutes"]["low"], out["totals"]["minutes"]["high"]) == (30, 80)
    line = out["calculation"][2]
    expr = line.split(" = ", 1)[1].rsplit(" = ", 1)[0]
    assert expr == "max([0–50] (E1), [0–50] (E1~2026-02-03-individual_therapy)) + 30 (E2)", line
    assert _value(expr) == (30, 80)
    day = next(g for g in out["groups"] if g["group"] == "2026-02-03")
    assert day["minutes_calculation"] == "max([0–50] (E1), [0–50] (E1~2026-02-03-individual_therapy))"
    assert _value(day["minutes_calculation"]) == (day["minutes"]["low"], day["minutes"]["high"])


def test_every_operator_renders_alternatives_as_one_session(tmp_path):
    conn, _ = _disputed_type(tmp_path)
    alt = "max([0–50] (E1), [0–50] (E1~2026-02-03-individual_therapy))"
    comp = run(conn, ComplianceStep(scope=scope()))
    ev = comp["groups"][0]["evaluations"][0]
    assert ev["minutes_calculation"] == alt + " + 30 (E2)"
    assert _value(ev["minutes_calculation"]) == (ev["totals"]["minutes"]["low"], ev["totals"]["minutes"]["high"])
    tl = run(conn, TimelineStep(scope=scope(), kinds=["encounters"]))
    assert alt in tl["calculation"][0], tl["calculation"]
    cmp_ = run(conn, CompareStep(scope=scope(), split="2026-02-04"))
    before = next(g for g in cmp_["groups"] if g["side"] == "before")
    assert before["minutes_calculation"] == alt


def test_alternatives_split_by_a_group_are_rendered_where_they_fall(tmp_path):
    """Grouped by service type, each alternative is alone in its bucket: no max() across buckets."""
    conn, _ = _disputed_type(tmp_path)
    out = run(conn, CareStep(scope=scope(), group_by="service_type"))
    fam = next(g for g in out["groups"] if g["group"] == "family_therapy")
    assert fam["minutes_calculation"] == "[0–50] (E1)"


def test_idless_contact_alternatives_render_as_one_session(tmp_path):
    """Unidentified contacts' alternatives share the key before '~' (#74)."""
    conn, res = build(tmp_path, [
        event("note-fam", eid=None, stype="family_therapy", date="2026-02-03", contact=[("10:00", "10:50")]),
        event("note-ind", eid=None, stype="individual_therapy", date="2026-02-03", contact=[("10:00", "10:50")])])
    assert len(res.encounters) == 2 and len({project.session_group_key(e) for e in res.encounters}) == 1
    out = run(conn, CareStep(scope=scope()))
    expr = out["calculation"][2].split(" = ", 1)[1].rsplit(" = ", 1)[0]
    assert expr.startswith("max(") and expr.count("[0–50]") == 2, expr
    assert _value(expr) == (0, 50) == (out["totals"]["minutes"]["low"], out["totals"]["minutes"]["high"])


def test_session_group_key_is_what_aggregate_groups_by(tmp_path):
    _, res = _disputed_type(tmp_path)
    groups = {}
    for e in res.encounters:
        groups.setdefault(project.session_group_key(e), []).append(e["encounter_key"])
    assert sorted(map(len, groups.values())) == [1, 2]
    rows = [{**e, "claim_ids": [], "flags": []} for e in res.encounters]
    assert project.aggregate(rows)["sessions"] == {"low": 1, "high": 2, "status": "bounded"}


# ---------------------------------------------------------------- #79 goal-counted non-psychotherapy visits

def _medication_week(tmp_path, *extra):
    return build(tmp_path, [
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        plan("PLAN", "patient_present_minutes", 30),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", contact=[("09:00", "09:20")]),
        event("note-E2", eid="E2", date="2026-02-04", stype="individual_therapy", contact=[("10:00", "10:50")]),
        *extra])


def test_compliance_lists_a_goal_counted_medication_visit_as_counted(tmp_path):
    conn, _ = _medication_week(tmp_path)
    out = run(conn, ComplianceStep(scope=scope()))
    ev = out["groups"][0]["evaluations"][0]
    med = next(r for r in ev["requirements"] if r["metric"] == "sessions")
    assert med["status"] == "MET", med
    assert [e["encounter"] for e in out["exclusions"]] == [], out["exclusions"]
    assert [(c["encounter"], c["counts"]) for c in med["counted_non_psychotherapy"]] == [("E1", "yes")], med
    reason = med["counted_non_psychotherapy"][0]["reason"]
    assert reason.startswith("attended medication_management visit with the patient present: counts for a goal "
                             "that counts medication_management"), reason
    assert not re.search(r"\d", reason), reason          # nothing the post-check would accept as a stated number
    therapy = next(r for r in ev["requirements"] if r["metric"] == "patient_present_minutes")
    assert "counted_non_psychotherapy" not in therapy


def test_compliance_minutes_expression_leaves_out_non_psychotherapy_rows(tmp_path):
    conn, _ = _medication_week(tmp_path)
    ev = run(conn, ComplianceStep(scope=scope()))["groups"][0]["evaluations"][0]
    assert "?" not in ev["minutes_calculation"] and "E1" not in ev["minutes_calculation"], ev["minutes_calculation"]
    assert ev["minutes_calculation"] == "50 (E2)"
    assert _value(ev["minutes_calculation"]) == (ev["totals"]["minutes"]["low"], ev["totals"]["minutes"]["high"])
    assert ev["minutes_service_types"] == ALL_THERAPY_SORTED
    therapy = next(r for r in ev["requirements"] if r["metric"] == "patient_present_minutes")
    assert (therapy["value"]["low"], therapy["value"]["high"], therapy["status"]) == (50, 50, "MET")


def test_a_medication_no_show_is_still_not_counted(tmp_path):
    conn, _ = build(tmp_path, [
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", disposition="no_show",
              present="no")])
    out = run(conn, ComplianceStep(scope=scope()))
    assert out["groups"][0]["status"] == "NOT_MET"
    assert [e["encounter"] for e in out["exclusions"]] == ["E1"]
    assert out["groups"][0]["evaluations"][0]["requirements"][0]["counted_non_psychotherapy"] == []


def test_a_medication_visit_without_a_medication_goal_stays_not_counted(tmp_path):
    conn, _ = build(tmp_path, [
        plan("PLAN", "patient_present_minutes", 30),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", contact=[("09:00", "09:20")])])
    out = run(conn, ComplianceStep(scope=scope()))
    assert [(e["encounter"], e["reason"]) for e in out["exclusions"]] == [
        ("E1", "not a psychotherapy service (medication_management)")]


def test_therapy_or_medication_identity_dispute_shows_psychotherapy_minutes_only(tmp_path):
    """One encounter is individual therapy or medication management: psychotherapy minutes are 0–50, and the shown
    expression and the shown bound agree (the union with the medication row would be unbounded)."""
    conn, _ = build(tmp_path, [
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        plan("PLAN2", "patient_present_minutes", 30),
        event("note-a", eid="E1", stype="individual_therapy", date="2026-02-03", contact=[("09:00", "09:50")]),
        event("note-b", eid="E1", stype="medication_management", date="2026-02-03", contact=[("09:00", "09:50")])])
    out = run(conn, ComplianceStep(scope=scope()))
    ev = out["groups"][0]["evaluations"][0]
    assert (ev["totals"]["minutes"]["low"], ev["totals"]["minutes"]["high"]) == (0, 50), ev["totals"]
    assert "?" not in ev["minutes_calculation"], ev["minutes_calculation"]
    assert _value(ev["minutes_calculation"]) == (0, 50)
    med = next(r for r in ev["requirements"] if r["metric"] == "sessions")
    assert [c["counts"] for c in med["counted_non_psychotherapy"]] == ["uncertain"], med
    assert "disputed" in med["counted_non_psychotherapy"][0]["reason"]
    assert med["status"] == "UNDETERMINED"
    assert "minutes 0–50" in out["calculation"][0], out["calculation"]


def test_mixed_minutes_goal_over_medication_stays_a_lower_bound(tmp_path):
    """Guard: a minutes goal over [individual_therapy, medication_management] is still judged on the union, a lower
    bound only (#48); only the shown evaluation minutes became psychotherapy minutes."""
    conn, _ = build(tmp_path, [
        plan("PLAN", "patient_present_minutes", 60, counted=["individual_therapy", "medication_management"]),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", contact=[("09:00", "09:20")]),
        event("note-E2", eid="E2", date="2026-02-04", stype="individual_therapy", contact=[("10:00", "10:50")])])
    ev = run(conn, ComplianceStep(scope=scope()))["groups"][0]["evaluations"][0]
    r = ev["requirements"][0]
    assert (r["status"], r["value"]["low"], r["value"]["high"]) == ("UNDETERMINED", 50, None), r
    assert "lower bound" in r["reason"]
    assert ev["minutes_calculation"] == "50 (E2)"
    assert (ev["totals"]["minutes"]["low"], ev["totals"]["minutes"]["high"]) == (50, 50)
    assert [c["encounter"] for c in r["counted_non_psychotherapy"]] == ["E1"]


def test_a_medication_goal_that_may_have_lapsed_still_lists_the_visit_as_counted(tmp_path):
    """A later revision of the sessions metric does not restate the medication goal (#49): the week is evaluated with
    and without it. The visit counts in one alternative, so it is listed under that requirement and is not an
    exclusion (an exclusion is a row that no goal in any alternative counts)."""
    conn, _ = build(tmp_path, [
        plan("PLAN", "sessions", 1, counted=["medication_management"], start="2026-01-26"),
        plan("REV", "sessions", 1, counted=["individual_therapy"]),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", contact=[("09:00", "09:20")]),
        event("note-E2", eid="E2", date="2026-02-04", stype="individual_therapy", contact=[("10:00", "10:50")])])
    out = run(conn, ComplianceStep(scope=scope()))
    evs = out["groups"][0]["evaluations"]
    assert len(evs) == 2, evs
    listed = [[c["encounter"] for r in ev["requirements"] for c in r.get("counted_non_psychotherapy", ())]
              for ev in evs]
    assert sorted(listed) == [[], ["E1"]], listed
    assert out["exclusions"] == []


def test_a_medication_visit_on_a_day_no_plan_covers_stays_excluded(tmp_path):
    conn, _ = build(tmp_path, [
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        event("note-E0", eid="E0", date="2026-02-01", stype="medication_management", contact=[("09:00", "09:20")]),
        event("note-E1", eid="E1", date="2026-02-03", stype="medication_management", contact=[("09:00", "09:20")])])
    out = run(conn, ComplianceStep(scope=scope(start="2026-01-26")))
    assert {g["week_start"]: g["status"] for g in out["groups"]} == {"2026-01-26": "NO_PLAN", "2026-02-02": "MET"}
    assert [e["encounter"] for e in out["exclusions"]] == ["E0"]


# ---------------------------------------------------------------- #73 a long sum keeps each max() whole

def _row(key, day, lo, hi, eligible="uncertain"):
    mrn, rest = key.split("|", 1)
    return {"encounter_key": key, "mrn": mrn, "encounter_id": rest.split("~", 1)[0], "service_date": day,
            "eligible": eligible, "minutes_low": lo, "minutes_high": hi}


def test_truncated_minutes_expression_does_not_cut_an_alternative_group():
    from backbone.operators import _minutes_expr
    rows = [_row(f"P1|E{i:02d}", "2026-02-02", 10, 10, "yes") for i in range(3)]
    rows.insert(1, _row("P1|E99", "2026-02-02", 50, 50))
    rows.append(_row("P1|E99~2026-02-09-individual_therapy", "2026-02-09", 50, 50))
    expr = _minutes_expr(rows, n=3)
    assert expr == ("sum over 5 encounters (first 3 and 1 identity alternative of them: 10 (E00) + "
                    "max([0–50] (E99), [0–50] (E99~2026-02-09-individual_therapy)) + 10 (E01) …)"), expr
    assert _minutes_expr(rows[:3], n=3) == "10 (E00) + [0–50] (E99) + 10 (E01)"
