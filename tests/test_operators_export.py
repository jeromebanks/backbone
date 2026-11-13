"""Operators and export: scope clipping (#20), graph integrity (#24), SQLite variable limits and detail caps (#25),
R0 rejections in output (#39), same-label documents (#40).

Fixtures build small abstractions through the real ingest + reconcile path with a fake extractor (no LLM), as in
`tests/test_isolation.py`. Patient facts here are synthetic and live only in this test file.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from backbone import ingest as ingest_mod
from backbone import operators
from backbone.db import DEFAULT_DB, connect, connect_readonly
from backbone.export import _claims, build_abstraction, build_graph
from backbone.ingest import ingest
from backbone.project import SqlLog
from backbone.query import CareStep, CompareStep, QueryPlan, Scope, TimelineStep, execute_plan
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, ServiceEvent

VAR_LIMIT = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER


def _event(eid: str | None, day: str, quote: str, start="10:00", end="10:50") -> ServiceEvent:
    return ServiceEvent(
        encounter_id=eid, related_encounter_id=None, appointment_id=None, service_date=day,
        service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
        disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
        patient_departure=None, patient_contact_intervals=[{"start": start, "end": end}],
        nontherapeutic_intervals=[], stated_minutes=None, clinicians=[], quotes=[quote])


def _build(tmp_path, monkeypatch, docs: list[dict]):
    """docs: [{file, label, mrn, title, lines: [str], events: [ServiceEvent]}]. Each document's text is a header
    (label, patient) followed by `lines`; an event quote that is not one of the lines is unverifiable (R0)."""
    conn = connect(tmp_path / "ops.db")
    extractions, files = {}, []
    for d in docs:
        f = tmp_path / d["file"]
        f.write_text(f"Document ID: {d['label']}\nPatient: Pat {d['mrn']} | MRN {d['mrn']}\n" + "\n".join(d["lines"]) + "\n")
        files.append(f)
        extractions[d["file"]] = Extraction(
            document=DocumentInfo(document_id=d["label"], title=d.get("title", d["file"]), signed=True, signed_at=None,
                                  received_at=None, finality="final", patient_name=f"Pat {d['mrn']}",
                                  patient_mrn=d["mrn"], patient_dob=None, relations=[]),
            service_events=d["events"], assessments=[], observations=[], plan_requirements=[])
        extractions[d["file"]].document.relations = d.get("relations", [])

    def fake_extract(sha, filename, text, **kw):
        return extractions[filename], {"from_cache": False, "latency_ms": 0}
    monkeypatch.setattr(ingest_mod, "extract_document", fake_extract)
    monkeypatch.setattr("backbone.extract.complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    stats = ingest(conn, files, log=lambda *a: None, workers=1)
    assert not stats["failed"] and not stats["quarantined"], stats
    reconcile_patients(conn, stats["affected_patients"])
    conn.commit()
    return conn


def _run(conn, step) -> dict:
    return execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]


def _doc(file, label, mrn, events, *, title=None, extra_lines=()):
    return {"file": file, "label": label, "mrn": mrn, "title": title or file,
            "lines": [q for e in events for q in e.quotes] + list(extra_lines), "events": events}


# ------------------------------------------------------------------------------------------- #20 compare scope

@pytest.fixture
def three_months(tmp_path, monkeypatch):
    evs = [_event("E1", "2026-01-15", "Individual therapy E1 2026-01-15 10:00-10:50."),
           _event("E2", "2026-02-04", "Individual therapy E2 2026-02-04 10:00-10:50."),
           _event("E3", "2026-03-04", "Individual therapy E3 2026-03-04 10:00-10:50.")]
    return _build(tmp_path, monkeypatch, [_doc("notes.txt", "NOTES", "P1", evs)])


@pytest.mark.parametrize("split", ["2026-01-01", "2026-03-01"])
def test_compare_split_outside_scope_never_expands_scope(three_months, split):
    """#20: for a Feb 2–8 scope, a split before or after the scope must not pull in January or March care."""
    sc = Scope(patients=["P1"], start="2026-02-02", end="2026-02-08", include_evidence=False)
    out = _run(three_months, CompareStep(scope=sc, split=split))
    sides = out["groups"]
    assert sides, out["notes"]
    for s in sides:
        a, b = s["period"].split("..")
        assert "2026-02-02" <= a <= b <= "2026-02-08", s["period"]
        assert s["weeks"] == 1.0, s
    assert sorted({e for s in sides for e in s["encounters"]}) == ["E2"]
    assert [f["encounter"] for f in out["facts"]] == ["E2"]
    assert any("not inside the scope" in n for n in out["notes"]), out["notes"]


def test_compare_split_inside_scope_unchanged(three_months):
    sc = Scope(patients=["P1"], start="2026-02-02", end="2026-02-08", include_evidence=False)
    out = _run(three_months, CompareStep(scope=sc, split="2026-02-05"))
    assert [(s["side"], s["period"], s["weeks"]) for s in out["groups"]] == [
        ("before", "2026-02-02..2026-02-04", 0.43), ("after", "2026-02-05..2026-02-08", 0.57)]
    assert not any("not inside the scope" in n for n in out["notes"])


# ------------------------------------------------------------------------------------------- #24 graph export

def _check_graph(g: dict):
    ids = [n["id"] for n in g["nodes"]]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    dangling = [e for e in g["edges"] if e["from"] not in set(ids) or e["to"] not in set(ids)]
    assert not dangling, dangling[:5]


@pytest.mark.skipif(not DEFAULT_DB.exists(), reason="no corpus database")
def test_corpus_graph_has_no_dangling_edges():
    """#24: every edge endpoint of the shipped patient's graph is a node (12 COUNTED_IN edges dangled)."""
    conn = connect_readonly()
    g = build_graph(build_abstraction(conn, "HG-M042"))
    _check_graph(g)
    types = {e["type"] for e in g["edges"]}
    assert {"COUNTED_IN", "CORRECTS", "DOCUMENTED_BY", "STATED_IN"} <= types, types   # not vacuous


def test_graph_keeps_same_label_documents_apart(tmp_path, monkeypatch):
    """#24/#40: document nodes are identified by sha256, so two documents labelled NOTE are two nodes."""
    a = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, primary note.")
    b = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, co-therapist note.")
    conn = _build(tmp_path, monkeypatch, [_doc("note_a.txt", "NOTE", "P1", [a]), _doc("note_b.txt", "NOTE", "P1", [b])])
    g = build_graph(build_abstraction(conn, "P1"))
    _check_graph(g)
    docs = [n for n in g["nodes"] if n["type"] == "Document"]
    assert len(docs) == 2 and {n["doc_id"] for n in docs} == {"NOTE"}
    enc = next(n["id"] for n in g["nodes"] if n["type"] == "Encounter")
    assert sorted(e["to"] for e in g["edges"] if e["from"] == enc and e["type"] == "DOCUMENTED_BY") == \
        sorted(n["id"] for n in docs)


# ------------------------------------------------------------------------------------------- #25 variable limits

N_BIG = 1200


@pytest.fixture
def many_encounters(tmp_path, monkeypatch):
    """One patient, 1200 identified encounters on distinct days, all in one document (one claim each)."""
    from datetime import date, timedelta
    d0 = date(2024, 1, 1)
    evs = [_event(f"E{i:04d}", str(d0 + timedelta(days=i)), f"Individual therapy E{i:04d} {d0 + timedelta(days=i)} 10:00-10:50.")
           for i in range(N_BIG)]
    return _build(tmp_path, monkeypatch, [_doc("big.txt", "BIG", "P1", evs)])


BIG_SCOPE = dict(patients="all", start="2024-01-01", end="2027-12-31")


def test_collection_queries_survive_low_variable_limit(many_encounters):
    """#25: with SQLite's historical limit of 999 variables, timeline/compare/care over 1200 encounters must
    neither fail ('too many SQL variables') nor return unbounded detail."""
    conn = many_encounters
    conn.setlimit(VAR_LIMIT, 999)
    sc = Scope(include_excluded=True, **BIG_SCOPE)
    tl = _run(conn, TimelineStep(scope=sc, kinds=["encounters", "documents", "decisions"]))
    cmp_ = _run(conn, CompareStep(scope=sc, split="2025-06-01"))
    care = _run(conn, CareStep(scope=sc, group_by="patient"))
    assert care["totals"]["sessions"]["low"] == N_BIG and tl["totals"]["sessions"]["low"] == N_BIG
    assert sum(s["sessions"]["low"] for s in cmp_["groups"]) == N_BIG          # totals stay complete
    lim = operators.DETAIL_LIMIT
    assert len([f for f in tl["facts"] if f["kind"] == "encounter"]) == lim
    assert len(cmp_["facts"]) == lim and len(cmp_["evidence"]) <= lim
    assert any("showing" in n for n in tl["notes"]) and any("showing" in n for n in cmp_["notes"])


def _strip_sql(x):
    return {k: v for k, v in x.items() if k != "sql"}


@pytest.mark.parametrize("step", [
    TimelineStep(scope=Scope(include_excluded=True, **BIG_SCOPE), kinds=["encounters", "documents", "decisions"]),
    CompareStep(scope=Scope(**BIG_SCOPE), split="2025-06-01"),
    CareStep(scope=Scope(include_excluded=True, **BIG_SCOPE), group_by="week"),
], ids=["timeline", "compare", "care"])
def test_batched_lookups_match_single_statement(many_encounters, step):
    """#25: batching changes only the logged SQL, never the results. (The batched run goes first: sqlite3 caches
    prepared statements, and the variable limit is only checked when a statement is prepared.)"""
    conn = many_encounters
    high = conn.setlimit(VAR_LIMIT, 50)
    batched = _run(conn, step)
    conn.setlimit(VAR_LIMIT, high)
    whole = _run(conn, step)
    assert _strip_sql(batched) == _strip_sql(whole)
    assert len(batched["sql"]) > len(whole["sql"])        # the long IN-lists really were split


def test_shared_helpers_batch_long_id_lists(many_encounters):
    conn = many_encounters
    conn.setlimit(VAR_LIMIT, 999)
    ids = [r[0] for r in conn.execute("SELECT claim_id FROM claims WHERE kind='service_event' ORDER BY claim_id")]
    keys = [r[0] for r in conn.execute("SELECT encounter_key FROM encounters")]
    assert len(ids) == len(keys) == N_BIG
    log = SqlLog()
    assert len(operators._evidence(conn, ids, log)) == N_BIG
    assert operators._docs_of(conn, ids, log) == ["BIG"]
    assert operators._decisions(conn, keys, log, rules=("R0", "R1")) == []
    assert operators._conflicts(conn, keys, log) == []
    assert len(_claims(conn, ids)) == N_BIG


def test_batched_relations_and_conflicts_keep_patients_apart(tmp_path, monkeypatch):
    """#25 with #2's isolation: P1 and P2 both have an encounter E1 and a document labelled NOTE. P1's E1 has two
    notes that disagree on the contact interval (a conflict) and a companion relation; P2's NOTE corrects its own
    E1. With a variable limit of 3 the relation lookup takes the per-document path; results must not change."""
    from test_isolation import COMPANION_LINE, CORRECTION_LINE, _companion, _correction
    a = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, primary note.")
    b = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:40, co-therapist note.", end="10:40")
    c = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, other patient.")
    p1a = _doc("p1_a.txt", "NOTE", "P1", [a], title="P1 primary", extra_lines=[COMPANION_LINE])
    p1a["relations"] = [_companion()]
    p2 = _doc("p2.txt", "NOTE", "P2", [c], title="P2 note", extra_lines=[CORRECTION_LINE])
    p2["relations"] = [_correction()]
    conn = _build(tmp_path, monkeypatch, [p1a, _doc("p1_b.txt", "NOTE", "P1", [b], title="P1 co-therapist"), p2])
    step = TimelineStep(scope=Scope(patients="all", start="2026-01-05", end="2026-01-11"),
                        kinds=["encounters", "documents", "decisions"])
    high = conn.setlimit(VAR_LIMIT, 3)
    batched = _run(conn, step)
    conn.setlimit(VAR_LIMIT, high)
    whole = _run(conn, step)
    assert _strip_sql(batched) == _strip_sql(whole)
    assert any("FROM claims WHERE kind='relation' AND verified=1 AND sha256 IN (?" in s["sql"]
               and "VALUES" not in s["sql"] for s in batched["sql"])                  # the per-document path ran
    assert whole["conflicts"], "fixture should produce a conflict on P1's E1"
    rels = {d["title"]: sorted(r["type"] for r in d.get("relations", []))
            for d in whole["facts"] if d["kind"] == "document"}
    assert rels == {"P1 primary": ["companion_record"], "P1 co-therapist": [], "P2 note": ["corrects_field"]}


def test_timeline_with_many_patients_in_scope(many_encounters):
    """#25: an explicit patient list longer than the variable limit (assessments/observations lookups)."""
    conn = many_encounters
    conn.setlimit(VAR_LIMIT, 999)
    pts = ["P1"] + [f"X{i}" for i in range(N_BIG)]
    out = _run(conn, TimelineStep(scope=Scope(patients=pts, start="2024-01-01", end="2027-12-31"),
                                  kinds=["assessments", "observations"]))
    assert out["facts"] == []


# ------------------------------------------------------------------------------------------- #39 R0 rejections

@pytest.fixture
def fabricated(tmp_path, monkeypatch):
    """E1 is documented by GOOD (verified) and claimed again by BAD with a quote that is not in BAD's text.
    E2 is claimed only by BAD, with a fabricated quote, so no E2 encounter exists."""
    good = _doc("good.txt", "GOOD", "P1", [_event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50.")])
    bad = _doc("bad.txt", "BAD", "P1", [
        _event("E1", "2026-01-07", "Patient attended E1 for the full hour and was engaged throughout."),
        _event("E2", "2026-01-08", "Patient attended E2 for ninety minutes of family therapy work.")],
        extra_lines=["This record contains only administrative text about scheduling on 2026-01-07 and 2026-01-08."])
    # neither event quote is in BAD's text; the dates are, so the rejections keep them (an unstated date is #68's case)
    bad["lines"] = bad["lines"][-1:]
    return _build(tmp_path, monkeypatch, [good, bad])


def test_r0_rejections_appear_in_timeline(fabricated):
    conn = fabricated
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE verified=0").fetchone()[0] == 2
    out = _run(conn, TimelineStep(scope=Scope(patients=["P1"], start="2026-01-05", end="2026-01-11"),
                                  kinds=["encounters", "documents", "decisions"]))
    r0 = [x for x in out["exclusions"] if x.get("rule") == "R0"]
    assert sorted((x["records"], x["date"], x["encounter"]) for x in r0) == [(["BAD"], "2026-01-07", "E1"),
                                                                            (["BAD"], "2026-01-08", "E2")]
    assert all("quote not found" in x["reason"] for x in r0)
    # the rejection attaches to the surviving E1 encounter as a decision
    assert any(d["rule"] == "R0" and d["subject"] == "E1" for d in out["decisions"]), out["decisions"]
    # the CLI's compact readout (plan --summary) lists them like any other exclusion
    from backbone.summary import summarize
    step = TimelineStep(scope=Scope(patients=["P1"], start="2026-01-05", end="2026-01-11"), kinds=["encounters"])
    text = summarize(execute_plan(conn, QueryPlan(question="t", steps=[step])))
    assert "EXCLUDED E2 2026-01-08" in text, text


def test_r0_rejections_appear_in_care_exclusions(fabricated):
    sc = Scope(patients=["P1"], start="2026-01-05", end="2026-01-11", include_excluded=True)
    out = _run(fabricated, CareStep(scope=sc))
    assert out["totals"]["sessions"]["low"] == 1                     # BAD's claims never count
    assert sorted(x["encounter"] for x in out["exclusions"] if x.get("rule") == "R0") == ["E1", "E2"]
    # out of scope: the rejection is dated by the claim's own service date
    later = _run(fabricated, CareStep(scope=Scope(patients=["P1"], start="2026-01-08", end="2026-01-11",
                                                  include_excluded=True)))
    assert [x["encounter"] for x in later["exclusions"] if x.get("rule") == "R0"] == ["E2"]
    # a service-type filter applies to rejected claims too (the rejected claims are individual therapy)
    group = _run(fabricated, CareStep(scope=sc.model_copy(update={"service_types": ["group_therapy"]})))
    assert [x for x in group["exclusions"] if x.get("rule") == "R0"] == []


# ------------------------------------------------------------------------------------------- #40 same-label docs

@pytest.fixture
def same_label(tmp_path, monkeypatch):
    a = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, primary note.")
    b = _event("E1", "2026-01-07", "Individual therapy E1 2026-01-07 10:00-10:50, co-therapist note.")
    return _build(tmp_path, monkeypatch, [_doc("note_a.txt", "NOTE", "P1", [a], title="primary"),
                                          _doc("note_b.txt", "NOTE", "P1", [b], title="co-therapist")])


SL_SCOPE = Scope(patients=["P1"], start="2026-01-05", end="2026-01-11")


def test_same_label_documents_are_distinguishable(same_label):
    shas = sorted(r[0][:12] for r in same_label.execute("SELECT sha256 FROM documents"))
    tl = _run(same_label, TimelineStep(scope=SL_SCOPE, kinds=["encounters", "documents"]))
    docs = [f for f in tl["facts"] if f["kind"] == "document"]
    assert [d["doc_id"] for d in docs] == ["NOTE", "NOTE"]            # citations by label stay valid
    assert sorted(d["doc_sha"] for d in docs) == shas
    assert sorted(e["doc_sha"] for e in tl["evidence"]) == shas
    enc = next(f for f in tl["facts"] if f["kind"] == "encounter")
    assert sorted(enc["records"]) == [f"NOTE [{s}]" for s in shas]   # no longer collapsed into one "NOTE"
    care = _run(same_label, CareStep(scope=SL_SCOPE))
    assert sorted(care["facts"][0]["records"]) == [f"NOTE [{s}]" for s in shas]


def test_unique_labels_get_no_disambiguator(fabricated):
    tl = _run(fabricated, TimelineStep(scope=Scope(patients=["P1"], start="2026-01-05", end="2026-01-11"),
                                       kinds=["encounters", "documents"]))
    assert all("doc_sha" not in f for f in tl["facts"]) and all("doc_sha" not in e for e in tl["evidence"])
    assert next(f for f in tl["facts"] if f["kind"] == "encounter")["records"] == ["GOOD"]
