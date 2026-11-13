"""Reconciliation and projection follow-ups (#48, #49, #50, #58, #61, #62, #63, #64, #66, #68, #71).

Hand-built claims, no LLM. Weeks are Mon–Sun; 2026-02-02 is a Monday.
"""
from __future__ import annotations

import copy
import itertools
import json
import random
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import pytest

from backbone.db import connect
from backbone.query import CareStep, ComplianceStep, QueryPlan, Scope, execute_plan
from backbone.reconcile import Claim, load_claims, persist, reconcile_patient, reconcile_patients

from helpers import assessment, doc, enc, event, relation, with_docs

ALL_THERAPY = ["individual_therapy", "group_therapy", "family_therapy"]
WEEK = dict(start="2026-02-02", end="2026-02-08")
GROUP = ("10:00", "11:30")
VAR_LIMIT = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER
CORPUS_DB = Path(__file__).resolve().parents[1] / "out" / "backbone.db"
_n = itertools.count(5000)


# ---------------------------------------------------------------- builders

def plan(label, metric, threshold, *, comparator=">=", period="week_mon_sun", counted=ALL_THERAPY, excluded=(),
         present=True, start="2026-02-02", end="2026-02-28", sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    payload = {"metric": metric, "threshold": float(threshold), "comparator": comparator, "period": period,
               "counted_service_types": list(counted), "excluded_service_types": list(excluded),
               "requires_patient_present": present, "effective_start": start, "effective_end": end, "quote": "q"}
    return Claim(f"{sha}:plan_requirement:{next(_n)}", sha, label, "plan_requirement", None, None, payload, [], True)


def session(eid, day, stype, start, end, **kw) -> Claim:
    return event(f"note-{eid}", eid=eid, date=day, stype=stype, contact=[(start, end)], **kw)


def corr(label, field, old, new, eid="E1") -> Claim:
    return relation(label, "corrects_field", eid=eid, field=field, old=old, new=new)


def build(tmp_path, claims, name="t.db"):
    conn = connect(tmp_path / name)
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('P1', 'Test', '1990-01-01')")
    res = reconcile_patient("P1", claims)
    with conn:
        persist(conn, res)
    return conn, res


def run(conn, step):
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def weeks(conn, start="2026-02-02", end="2026-02-08"):
    step = ComplianceStep(scope=Scope(patients=["P1"], start=start, end=end, include_evidence=False))
    return {g["week_start"]: g for g in run(conn, step)["groups"]}


def minutes(e):
    return e["minutes_low"], e["minutes_high"], e["minutes_status"]


def dump(res) -> str:
    """The whole reconciliation result, byte for byte (decisions and conflicts keep their emitted order)."""
    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return json.dumps({"encounters": strip(res.encounters), "intervals": res.intervals, "plans": res.plans,
                       "assessments": res.assessments, "observations": res.observations,
                       "decisions": res.decisions, "conflicts": res.conflicts}, sort_keys=True, default=str)


# ---------------------------------------------------------------- #48 goals over non-psychotherapy types

def test_medication_management_goal_is_met_by_one_attended_visit(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        session("E1", "2026-02-03", "medication_management", "09:00", "09:20")))
    w = weeks(conn)["2026-02-02"]
    r = w["evaluations"][0]["requirements"][0]
    assert (r["status"], r["value"]["low"], r["value"]["high"]) == ("MET", 1, 1), r
    assert w["status"] == "MET"


def test_medication_management_goal_is_not_met_by_a_no_show(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        session("E1", "2026-02-03", "medication_management", "09:00", "09:20", disposition="no_show", present="no")))
    assert weeks(conn)["2026-02-02"]["status"] == "NOT_MET"


def test_disputed_therapy_or_medication_identity_is_uncertain_for_a_medication_goal(tmp_path):
    """The encounter is individual therapy or medication management; the medication goal must not be NOT_MET."""
    conn, res = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1, counted=["medication_management"]),
        event("note-a", stype="individual_therapy", date="2026-02-03", contact=[("09:00", "09:50")]),
        event("note-b", stype="medication_management", date="2026-02-03", contact=[("09:00", "09:50")])))
    r = weeks(conn)["2026-02-02"]["evaluations"][0]["requirements"][0]
    assert (r["value"]["low"], r["value"]["high"], r["status"]) == (0, 1, "UNDETERMINED"), r
    therapy = [e for e in res.encounters if e["service_type"] == "individual_therapy"]
    assert [e["eligible"] for e in therapy] == ["uncertain"]           # the psychotherapy side is unchanged


def test_minutes_goal_over_medication_management_stays_a_lower_bound(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "patient_present_minutes", 15, counted=["medication_management"]),
        session("E1", "2026-02-03", "medication_management", "09:00", "09:20")))
    r = weeks(conn)["2026-02-02"]["evaluations"][0]["requirements"][0]
    assert r["status"] == "UNDETERMINED" and "lower bound" in r["reason"]


# ---------------------------------------------------------------- #49 a revision that restates one goal

def _revision(tmp_path, *extra):
    return build(tmp_path, with_docs(
        plan("PLAN", "sessions", 2, counted=["individual_therapy"], start="2026-01-26"),
        plan("PLAN", "sessions", 1, counted=["group_therapy"], start="2026-01-26"),
        plan("REV", "sessions", 3, counted=["individual_therapy"], start="2026-02-02"),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50"),
        session("E2", "2026-02-03", "individual_therapy", "09:00", "09:50"),
        session("E3", "2026-02-04", "individual_therapy", "09:00", "09:50"),
        *extra))


def test_goal_omitted_by_a_revision_is_not_silently_dropped(tmp_path):
    conn, res = _revision(tmp_path)
    w = weeks(conn)["2026-02-02"]
    # REV's >= 3 individual is met; PLAN's >= 1 group (not restated) is missed: it may or may not still apply
    assert w["status"] == "UNDETERMINED", w
    assert any("not restated" in n for n in w["notes"]), w["notes"]
    lapsed = [d for d in res.decisions if d["rule"] == "R9" and d["outcome"] == "goal_not_restated"]
    assert len(lapsed) == 1 and "group_therapy" in lapsed[0]["reason"] and "REV" in lapsed[0]["reason"]


def test_goal_omitted_by_a_revision_and_met_gives_a_definite_verdict(tmp_path):
    conn, _ = _revision(tmp_path, session("E4", "2026-02-05", "group_therapy", "10:00", "11:00"))
    assert weeks(conn)["2026-02-02"]["status"] == "MET"


def test_restated_goal_is_superseded_not_kept_alongside(tmp_path):
    conn, res = _revision(tmp_path)
    w = weeks(conn)["2026-02-02"]
    individual = {r["goal"] for ev in w["evaluations"] for r in ev["requirements"]
                  if r.get("counted_service_types", ev["counted_service_types"]) == ["individual_therapy"]}
    assert individual == {">= 3"}                       # PLAN's >= 2 individual is replaced, never ANDed


# ---------------------------------------------------------------- #50 same start, different period

def test_weekly_and_monthly_goals_from_different_documents_are_independent(tmp_path):
    conn, _ = build(tmp_path, with_docs(
        plan("WEEKLY", "sessions", 2),
        plan("MONTHLY", "sessions", 8, period="month"),
        session("E1", "2026-02-02", "individual_therapy", "09:00", "09:50")))
    w = weeks(conn)["2026-02-02"]
    assert len(w["evaluations"]) == 1, w["evaluations"]          # one set holding both goals, not alternatives
    assert not any("conflicting" in n for n in w["notes"])
    assert w["status"] == "NOT_MET"                              # the weekly goal (1 < 2) is missed regardless


# ---------------------------------------------------------------- #58 batched patient lists in the projection

@pytest.mark.parametrize("op", ["care", "compliance"])
def test_projection_batches_long_patient_lists(tmp_path, op):
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "sessions", 1),
        session("E1", "2026-02-03", "individual_therapy", "09:00", "09:50")))
    pts = ["P1"] + [f"X{i:03d}" for i in range(59)]
    scope = Scope(patients=pts, include_evidence=False, **WEEK)
    step = CareStep(scope=scope) if op == "care" else ComplianceStep(scope=scope)
    high = conn.setlimit(VAR_LIMIT, 50)                 # batched run first: statements are cached once prepared
    batched = run(conn, step)
    conn.setlimit(VAR_LIMIT, high)
    whole = run(conn, step)
    strip = lambda x: {k: v for k, v in x.items() if k != "sql"}
    assert strip(batched) == strip(whole)
    assert len(batched["sql"]) > len(whole["sql"])


# ---------------------------------------------------------------- #61 ID-less matching after corrections

def test_idless_record_matches_on_the_corrected_service_type():
    claims = with_docs(
        event("note", stype="family_collateral", contact=[("10:00", "10:50")]),
        corr("corr", "service_type", "family_collateral", "family_therapy"),
        event("register", eid=None, etype="attendance_record", stype="family_therapy",
              arrival="10:00", departure="10:50"))
    for order in (claims, list(reversed(claims))):
        res = reconcile_patient("P1", copy.deepcopy(order))
        assert len(res.encounters) == 1, [e["encounter_key"] for e in res.encounters]
        e = enc(res)
        assert (e["service_type"], e["eligible"], *minutes(e)) == ("family_therapy", "yes", 50, 50, "established")


def test_idless_record_matches_any_service_type_of_the_identified_encounter():
    """R1 matched only the FIRST record's type; an ID'd encounter whose records disagree matches either."""
    claims = with_docs(
        event("note-b", stype="family_therapy", contact=[("09:00", "09:50")], sha="sha-a"),
        event("note-a", stype="individual_therapy", contact=[("09:00", "09:50")], sha="sha-b"),
        event("register", eid=None, etype="attendance_record", stype="individual_therapy",
              arrival="09:00", departure="09:50", sha="sha-c"))
    res = reconcile_patient("P1", claims)
    assert not any(e["encounter_key"].startswith("P1|U-") for e in res.encounters), \
        [e["encounter_key"] for e in res.encounters]


# ---------------------------------------------------------------- #62 order-independent output

def _rich_patient():
    return with_docs(
        plan("PLAN", "sessions", 2), plan("PLAN", "therapy_days", 1),
        event("roster", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        event("note-g", scheduled=GROUP, nontherapeutic=[("10:45", "11:00", "break")]),
        corr("fix", "departure", "11:30", "11:15"),
        event("resent", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("resent", "retransmits_original", eid="E1"),
        event("note-a", eid="E2", date="2026-02-03", stype="individual_therapy", contact=[("09:00", "09:50")]),
        event("note-b", eid="E2", date="2026-02-03", stype="individual_therapy", contact=[("09:10", "09:50")]),
        event("sched", eid="E2", date="2026-02-03", etype="schedule_listing", stype="individual_therapy",
              scheduled=("09:00", "09:50")),
        event("reg", eid=None, date="2026-02-03", etype="attendance_record", stype="individual_therapy",
              arrival="09:00", departure="09:50"),
        event("note-c", eid="E3", date="2026-02-04", stype="individual_therapy", contact=[("13:00", "13:50")]),
        event("note-d", eid="E3", date="2026-02-05", stype="group_therapy", contact=[("13:00", "13:50")]),
        event("call", eid=None, date="2026-02-05", stype="outreach_call", disposition="unknown"),
        assessment("phq-a", score=14, date="2026-02-02", form_id="F1"),
        assessment("phq-b", score=14, date="2026-02-02", form_id="F1"),
        relation("phq-b", "copies_measurement", form_id="F1"),
        assessment("phq-c", score=12, date="2026-02-04"), assessment("phq-d", score=11, date="2026-02-04"))


def test_reconcile_output_is_identical_for_any_claim_order():
    claims = _rich_patient()
    want = dump(reconcile_patient("P1", copy.deepcopy(claims)))
    rng = random.Random(62)
    for _ in range(25):
        shuffled = copy.deepcopy(claims)
        rng.shuffle(shuffled)
        assert dump(reconcile_patient("P1", shuffled)) == want


@pytest.mark.skipif(not CORPUS_DB.exists(), reason="no corpus database")
def test_corpus_patient_reconciles_identically_in_any_claim_order():
    conn = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    claims = load_claims(conn, "HG-M042")
    want = dump(reconcile_patient("HG-M042", copy.deepcopy(claims)))
    rng = random.Random(42)
    for _ in range(10):
        shuffled = copy.deepcopy(claims)
        rng.shuffle(shuffled)
        assert dump(reconcile_patient("HG-M042", shuffled)) == want


# ---------------------------------------------------------------- #63 correction resolution by reachability

def _old_resolve(v0, edges):
    """The path-enumerating resolution replaced in #63, kept as the reference for terminals and used corrections."""
    succ = defaultdict(list)
    for e in edges:
        succ[e[0]].append(e)
    out = defaultdict(list)
    stack = [(v0, [], (v0,))]
    while stack:
        v, path, seen = stack.pop()
        nxt = sorted(succ.get(v, []), key=lambda e: e[2].claim_id)
        if not nxt:
            out[v].append(path)
        for e in nxt:
            if e[1] in seen:
                for x in seen[seen.index(e[1]):]:
                    out[x].append(path + [e])
            else:
                stack.append((e[1], path + [e], seen + (e[1],)))
    return out


class _C:
    def __init__(self, i):
        self.claim_id = f"c{i:04d}"


@pytest.mark.parametrize("graph", [
    [(0, 1), (1, 2)],                                  # chain
    [(0, 1), (0, 2)],                                  # competing
    [(0, 1), (1, 0)],                                  # cycle
    [(0, 1), (1, 0), (1, 2)],                          # cycle with an exit
    [(0, 1), (1, 2), (2, 1), (0, 3)],                  # cycle off the start, plus a sink
    [(0, 1), (0, 2), (1, 3), (2, 3), (3, 4), (5, 0)],  # diamond, and an edge into the start
    [(0, 1), (0, 1), (1, 2), (1, 2)],                  # restated chain
], ids=["chain", "competing", "cycle", "cycle-exit", "side-cycle", "diamond", "restated"])
def test_reachability_resolution_matches_path_enumeration(graph):
    from backbone.reconcile import _resolve
    edges = [(a, b, _C(i)) for i, (a, b) in enumerate(graph)]
    old, new = _old_resolve(0, edges), _resolve(0, edges)
    assert set(old) == set(new)
    used = lambda r: {e[2].claim_id for v in r.values() for x in v for e in (x if isinstance(x, list) else [x])}
    assert used(new) == {e[2].claim_id for v in old.values() for p in v for e in p}
    acyclic = graph not in ([(0, 1), (1, 0)], [(0, 1), (1, 0), (1, 2)], [(0, 1), (1, 2), (2, 1), (0, 3)])
    if acyclic:                                       # with a cycle, provenance is by reachability (a superset)
        for t in old:
            assert {e[2].claim_id for e in new[t]} == {e[2].claim_id for p in old[t] for e in p}


def test_restated_chain_and_dense_graph_resolve_quickly():
    chain = [corr(f"doc{i}", "departure", a, b) for i in range(30) for a, b in (("11:30", "11:15"), ("11:15", "11:00"))]
    nodes = [f"12:{m:02d}" for m in range(20)]
    dense = [corr(f"dense{i}-{j}", "arrival", nodes[i], nodes[j]) for i in range(20) for j in range(i + 1, 20)]
    claims = with_docs(event("roster", etype="attendance_record", arrival="12:00", departure="11:30",
                             scheduled=("10:00", "11:30")), *chain, *dense)
    t0 = time.perf_counter()
    res = reconcile_patient("P1", claims)
    assert time.perf_counter() - t0 < 1          # path enumeration took ~7 s here
    e = enc(res)
    assert "departure 11:30 replaced by 11:00" not in json.dumps(res.decisions)   # each edge is its own decision
    fixed = [d for d in res.decisions if d["outcome"] == "field_corrected"]
    assert len(fixed) == len(chain) + len(dense)                                  # one decision per applied edge
    assert not any(d["outcome"] == "correction_not_applied" for d in res.decisions)
    assert e["calculation"].startswith("12:19–11:00") or "unknown" in e["minutes_status"], e["calculation"]


# ---------------------------------------------------------------- #64 a correction that only reached an excluded copy

def test_correction_matching_only_an_excluded_copy_is_not_applied():
    fix = corr("fix", "departure", "11:30", "11:15")
    claims = with_docs(
        event("roster", etype="attendance_record", arrival="10:00", departure="11:15", scheduled=GROUP),
        event("resent", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("resent", "retransmits_original", eid="E1"),
        fix)
    res = reconcile_patient("P1", claims)
    e = enc(res)
    assert fix.claim_id not in e["claim_ids"]
    na = [d for d in res.decisions if d["outcome"] == "correction_not_applied"]
    assert len(na) == 1 and "excluded" in na[0]["reason"] and "resent" in na[0]["reason"], res.decisions
    assert not any(d["outcome"] == "field_corrected" for d in res.decisions)
    assert minutes(e) == (75, 75, "established")


def test_correction_reaching_a_contributing_record_and_a_copy_is_applied():
    fix = corr("fix", "departure", "11:30", "11:15")
    claims = with_docs(
        event("roster", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        event("resent", etype="attendance_record", arrival="10:00", departure="11:30", scheduled=GROUP),
        relation("resent", "retransmits_original", eid="E1"),
        fix)
    res = reconcile_patient("P1", claims)
    assert fix.claim_id in enc(res)["claim_ids"]
    assert sorted(d["reason"].split()[0] for d in res.decisions if d["outcome"] == "field_corrected") == ["resent", "roster"]


# ---------------------------------------------------------------- #66 disagreeing schedules

def _two_schedules(disposition="attended_full"):
    return with_docs(
        event("note-a", stype="individual_therapy", disposition=disposition, scheduled=("10:00", "10:50")),
        event("note-b", stype="individual_therapy", disposition=disposition, scheduled=("10:00", "11:00")))


def test_disagreeing_schedules_of_attended_full_records_are_disputed_bounds():
    claims = _two_schedules()
    for order in (claims, list(reversed(claims))):
        res = reconcile_patient("P1", copy.deepcopy(order))
        e = enc(res)
        assert minutes(e) == (50, 60, "disputed"), e["calculation"]
        assert any(c["field"] == "scheduled_interval" for c in res.conflicts)


def test_unknown_minutes_upper_bound_is_the_largest_schedule():
    claims = _two_schedules(disposition="attended")
    for order in (claims, list(reversed(claims))):
        e = enc(reconcile_patient("P1", copy.deepcopy(order)))
        assert minutes(e) == (0, 60, "unknown"), e["calculation"]


def test_tier_one_schedule_decides_over_a_listing():
    e = enc(reconcile_patient("P1", with_docs(
        event("note", stype="individual_therapy", disposition="attended_full", scheduled=("10:00", "10:50")),
        event("listing", etype="schedule_listing", stype="individual_therapy", disposition="attended",
              scheduled=("10:00", "11:00")))))
    assert minutes(e) == (50, 50, "established")


# ---------------------------------------------------------------- #68 R0 reason for an absent date

def test_absent_date_rejection_names_the_field_not_the_quote():
    ob = Claim("sha-n:observation:0", "sha-n", "NOTE", "observation", None, None,
               {"date": "2026-01-07", "domain": "sleep", "source": "patient_report", "statement": "s", "quote": "q"},
               [{"quote": "q", "line_start": 3, "line_end": 3, "match": "exact"},
                {"quote": None, "line_start": None, "line_end": None, "match": "grounding",
                 "grounding": {"date": "absent"}, "unverified_absent": ["date"]}], False)
    bad = Claim("sha-n:observation:1", "sha-n", "NOTE", "observation", None, None,
                {"date": "2026-01-07", "domain": "sleep", "source": "patient_report", "statement": "s", "quote": "x"},
                [{"quote": "x", "line_start": None, "line_end": None, "match": "missing"}], False)
    res = reconcile_patient("P1", with_docs(ob, bad))
    reasons = {d["claim_ids"][0]: d["reason"] for d in res.decisions if d["rule"] == "R0"}
    assert reasons[ob.claim_id] == ("NOTE observation: the date is not stated anywhere in the document (the extracted "
                                    "value was inferred)")
    assert "2026-01-07" not in reasons[ob.claim_id]          # the inferred value never reaches the reason
    assert reasons[bad.claim_id] == "NOTE observation: quote not found in source text"


# ---------------------------------------------------------------- #71 attribution provenance

def _attribution_db(tmp_path, *, notes=True):
    conn = connect(tmp_path / "attr.db")
    sha = "d" * 64
    conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) VALUES (?,?,?,?,?,?)",
                 (sha, "NOTE-1", json.dumps(["documents/n.txt"]), "MRN P1\nIndividual therapy", "P1", "2026-01-01"))
    conn.execute("INSERT INTO patients(mrn) VALUES ('P1')")
    ev = event("NOTE-1", stype="individual_therapy", contact=[("09:00", "09:50")])
    for cid, kind, payload, etype in ((f"{sha[:12]}:document:0", "document", {"signed": True, "finality": "final"}, None),
                                      (f"{sha[:12]}:service_event:0", "service_event", ev.payload, "clinical_note")):
        conn.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (cid, sha, "NOTE-1", "P1", kind, None, etype, json.dumps(payload), "[]", 1))
    if notes:
        conn.execute("INSERT INTO attribution_notes VALUES (?,?,?,?)",
                     (sha, "P1", "printed_mrn", "the extraction reported no MRN; the text prints one MRN, P1"))
    else:
        conn.execute("DROP TABLE attribution_notes")
    conn.commit()
    reconcile_patients(conn, ["P1"])
    return conn, sha


def test_attribution_basis_is_a_decision_and_in_the_export(tmp_path):
    from backbone.export import build_abstraction
    conn, sha = _attribution_db(tmp_path)
    rows = conn.execute("SELECT subject_key, rule, outcome, reason, claim_ids FROM decisions "
                        "WHERE outcome LIKE 'attributed_by_%'").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert (r["rule"], r["outcome"]) == ("R1", "attributed_by_printed_mrn")
    assert "NOTE-1" in r["reason"] and "prints one MRN" in r["reason"]
    assert sorted(json.loads(r["claim_ids"])) == [f"{sha[:12]}:document:0", f"{sha[:12]}:service_event:0"]
    assert "attributed_by_printed_mrn" in json.dumps(build_abstraction(conn, "P1"), default=str)


def test_reconcile_tolerates_a_database_without_attribution_notes(tmp_path):
    conn, _ = _attribution_db(tmp_path, notes=False)
    assert conn.execute("SELECT count(*) FROM encounters").fetchone()[0] == 1


# ---------------------------------------------------------------- #74 overlapping ID-less contacts of different types

def test_overlapping_idless_records_of_different_therapy_types_are_one_disputed_encounter(tmp_path):
    claims = with_docs(
        event("note-fam", eid=None, stype="family_therapy", date="2026-02-03", contact=[("10:00", "10:50")]),
        event("note-ind", eid=None, stype="individual_therapy", date="2026-02-03", contact=[("10:00", "10:50")]))
    conn, res = build(tmp_path, claims)
    assert {e["eligible"] for e in res.encounters} == {"uncertain"}, [(e["encounter_key"], e["eligible"]) for e in res.encounters]
    assert any(c["field"] == "service_type" and c["resolution"] == "disputed" for c in res.conflicts)
    assert not any("overlap" in f for e in res.encounters for f in e["flags"])
    totals = run(conn, CareStep(scope=Scope(patients=["P1"], include_evidence=False, **WEEK)))["totals"]
    assert (totals["sessions"]["low"], totals["sessions"]["high"]) == (0, 1), totals
    assert totals["minutes"]["high"] == 50, totals
    for t in ("family_therapy", "individual_therapy"):
        per = run(conn, CareStep(scope=Scope(patients=["P1"], include_evidence=False, service_types=[t], **WEEK)))
        assert (per["totals"]["sessions"]["low"], per["totals"]["sessions"]["high"]) == (0, 1), (t, per["totals"])


def test_idless_records_of_different_types_at_different_times_stay_two_encounters():
    res = reconcile_patient("P1", with_docs(
        event("note-fam", eid=None, stype="family_therapy", contact=[("10:00", "10:50")]),
        event("note-ind", eid=None, stype="individual_therapy", contact=[("14:00", "14:50")])))
    assert sorted(e["eligible"] for e in res.encounters) == ["yes", "yes"]


def test_a_schedule_alone_does_not_merge_contacts_of_different_types():
    """Only actual contact times show the patient was in one place: a no-show's schedule is not one."""
    res = reconcile_patient("P1", with_docs(
        event("register", stype="individual_therapy", etype="attendance_record", disposition="no_show", present="no",
              scheduled=("10:00", "10:50")),
        event("note-fam", eid=None, stype="family_therapy", contact=[("10:00", "10:50")])))
    assert sorted((e["service_type"], e["eligible"]) for e in res.encounters) == [
        ("family_therapy", "yes"), ("individual_therapy", "no")]


# ---------------------------------------------------------------- #72 unsupported metric

def test_unsupported_metric_evaluation_names_its_metric_and_goal():
    from backbone.project import evaluate_requirement
    ev = evaluate_requirement({"requirement_key": "k", "metric": "other", "comparator": ">=", "threshold": 1,
                               "counted_types": ALL_THERAPY}, {"sessions": {"low": 1, "high": 1}})
    assert (ev["status"], ev["metric"], ev["goal"]) == ("UNDETERMINED", "other", ">= 1")
    assert "unsupported" in ev["reason"]


def test_unsupported_metric_week_through_compliance_and_summary(tmp_path):
    """End to end: the 'other' goal counts only individual therapy, so the operator's per-requirement line (which
    formats `value`) runs too; neither compliance nor the summary readout may crash."""
    from backbone.summary import summarize
    conn, _ = build(tmp_path, with_docs(
        plan("PLAN", "other", 1, counted=["individual_therapy"]),
        plan("PLAN", "sessions", 1),
        session("E1", "2026-02-03", "individual_therapy", "09:00", "09:50")))
    step = ComplianceStep(scope=Scope(patients=["P1"], include_evidence=False, **WEEK))
    out = execute_plan(conn, QueryPlan(question="t", steps=[step]))
    w = out["results"][0]["groups"][0]
    other = [r for ev in w["evaluations"] for r in ev["requirements"] if r["metric"] == "other"]
    assert [r["status"] for r in other] == ["UNDETERMINED"] and w["status"] == "UNDETERMINED"
    assert summarize(out)
