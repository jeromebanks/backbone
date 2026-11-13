"""Patient-oriented exports derived from the database (never edited by hand):

out/abstraction/<MRN>.json        nested clinical abstraction: plans -> weeks -> encounters -> records -> passages
out/abstraction/<MRN>.graph.json  the same abstraction as a property graph (nodes + typed edges)
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import EXTRACTOR_VERSION, RULESET_VERSION
from .db import ROOT
from .intervals import fmt
from .operators import _batches
from .paths import safe_output_path
from .project import SqlLog, weekly_compliance
from .query import Scope

OUT = ROOT / "out" / "abstraction"


def _claims(conn, ids):
    if not ids:
        return []
    rows = []
    for b in _batches(conn, sorted(set(ids))):            # stay under SQLite's variable limit (#25)
        rows += conn.execute(f"SELECT c.claim_id, c.doc_label, c.sha256, c.kind, c.evidence_type, c.evidence, d.paths "
                             f"FROM claims c JOIN documents d USING(sha256) WHERE c.claim_id IN ({','.join('?' * len(b))}) "
                             f"ORDER BY c.doc_label, c.claim_id", b).fetchall()
    rows.sort(key=lambda r: (r["doc_label"], r["claim_id"]))
    return [{"claim_id": r["claim_id"], "doc_id": r["doc_label"], "sha256": r["sha256"],
             "file": Path(json.loads(r["paths"])[0]).name, "record_type": r["evidence_type"] or r["kind"],
             "passages": [{"lines": [s["line_start"], s["line_end"]], "quote": s["quote"]}
                          for s in json.loads(r["evidence"]) if s["line_start"]]} for r in rows]


def _claim_docs(conn, ids) -> dict[str, dict]:
    """claim_id -> {kind, sha256} for the claims behind decisions (graph edges need document identity, #24)."""
    out = {}
    for b in (_batches(conn, sorted(set(ids))) if ids else []):
        out.update({r["claim_id"]: {"kind": r["kind"], "sha256": r["sha256"]} for r in conn.execute(
            f"SELECT claim_id, kind, sha256 FROM claims WHERE claim_id IN ({','.join('?' * len(b))})", b)})
    return out


def build_abstraction(conn, mrn: str) -> dict:
    # Content only: reconciled_at (a timestamp) and the database-wide answer-cache fingerprint (which also hashes
    # other patients and the query/prompt versions) would change the committed export without a content change (#60).
    p = dict(conn.execute("SELECT mrn, name, dob, ruleset_version FROM patients WHERE mrn=?", (mrn,)).fetchone())
    docs = []
    for r in conn.execute("SELECT d.sha256, d.doc_label, d.paths, c.payload FROM documents d LEFT JOIN claims c "
                          "ON c.sha256=d.sha256 AND c.kind='document' WHERE d.patient_mrn=? ORDER BY d.doc_label", (mrn,)):
        m = json.loads(r["payload"] or "{}")
        docs.append({"doc_id": r["doc_label"], "sha256": r["sha256"], "files": [Path(x).name for x in json.loads(r["paths"])],
                     "title": m.get("title"), "signed": m.get("signed"), "signed_at": m.get("signed_at"),
                     "received_at": m.get("received_at"), "finality": m.get("finality")})
    decisions, conflicts = defaultdict(list), defaultdict(list)
    rows = conn.execute("SELECT * FROM decisions WHERE mrn=? ORDER BY decision_id", (mrn,)).fetchall()
    cdocs = _claim_docs(conn, [c for r in rows for c in json.loads(r["claim_ids"])])
    for r in rows:
        decisions[r["subject_key"]].append({"rule": r["rule"], "outcome": r["outcome"], "reason": r["reason"],
                                            "claims": [{"claim_id": c, **cdocs[c]} for c in json.loads(r["claim_ids"])
                                                       if c in cdocs]})
    for r in conn.execute("SELECT * FROM conflicts WHERE mrn=? ORDER BY conflict_id", (mrn,)):
        conflicts[r["subject_key"]].append({"field": r["field"], "resolution": r["resolution"],
                                            "candidates": json.loads(r["candidates"])})
    intervals = defaultdict(list)
    for r in conn.execute("SELECT * FROM encounter_intervals WHERE encounter_key IN "
                          "(SELECT encounter_key FROM encounters WHERE mrn=?)", (mrn,)):
        intervals[r["encounter_key"]].append({"kind": r["kind"], "start": fmt(r["start_min"]), "end": fmt(r["end_min"]),
                                              "label": r["label"]})
    encounters = []
    for r in conn.execute("SELECT * FROM v_encounter_week WHERE mrn=? ORDER BY service_date, encounter_key", (mrn,)):
        e = dict(r)
        e["claim_ids"], e["flags"] = json.loads(e["claim_ids"]), json.loads(e["flags"])
        e["intervals"] = intervals[e["encounter_key"]]
        e["records"] = _claims(conn, e.pop("claim_ids"))
        e["decisions"] = decisions[e["encounter_key"]]
        e["conflicts"] = conflicts[e["encounter_key"]]
        encounters.append(e)
    plans = []
    for r in conn.execute("SELECT * FROM plan_requirements WHERE mrn=? ORDER BY effective_start", (mrn,)):
        pr = dict(r)
        pr["counted_types"] = json.loads(pr["counted_types"])
        pr["evidence"] = _claims(conn, json.loads(pr.pop("claim_ids")))
        plans.append(pr)
    starts = [x["effective_start"] for x in plans if x["effective_start"]] + [e["service_date"] for e in encounters]
    ends = [x["effective_end"] for x in plans if x["effective_end"]] + [e["service_date"] for e in encounters]
    weeks = weekly_compliance(conn, mrn, date.fromisoformat(min(starts)), date.fromisoformat(max(ends)),
                              SqlLog(), Scope) if starts else []
    for w in weeks:
        for ev in w["evaluations"]:
            ev.pop("_rows", None)
            ev["encounters"] = [k.split("|", 1)[1] for k in ev["encounters"]]
            for r in ev.get("requirements", []):
                for c in r.get("counted_non_psychotherapy", []):
                    c["encounter"] = c["encounter"].split("|", 1)[-1]
    assessments = []
    for r in conn.execute("SELECT * FROM assessments WHERE mrn=? ORDER BY completed_date", (mrn,)):
        a = dict(r)
        a["item_scores"] = json.loads(a["item_scores"])
        a["evidence"] = _claims(conn, json.loads(a.pop("claim_ids")))
        a["copies_not_counted"] = _claims(conn, json.loads(a.pop("copy_claim_ids")))
        a["decisions"] = decisions[a["assessment_key"]]
        assessments.append(a)
    observations = [dict(r, claim_ids=json.loads(r["claim_ids"]))
                    for r in conn.execute("SELECT * FROM observations WHERE mrn=? ORDER BY obs_date, domain", (mrn,))]
    unmatched = {k: v for k, v in decisions.items() if not any(k == e["encounter_key"] for e in encounters)
                 and not k.startswith(f"{mrn}|PHQ") and "|plan|" not in k}
    return {
        "patient": p, "abstraction_version": {"extractor": EXTRACTOR_VERSION, "ruleset": RULESET_VERSION},
        "documents": docs, "treatment_plan_requirements": plans, "weeks": weeks, "encounters": encounters,
        "assessments": assessments, "observations": observations, "other_decisions": unmatched,
    }


def build_graph(ab: dict) -> dict:
    """Node identities: documents by sha256 (doc_label is not unique), encounters by their full `MRN|ID` key."""
    nodes, edges = [], []
    mrn = ab["patient"]["mrn"]

    def doc(x: dict) -> str:
        return f"doc:{x['sha256']}"
    nodes.append({"id": f"patient:{mrn}", "type": "Patient", **{k: ab["patient"][k] for k in ("mrn", "name", "dob")}})
    for d in ab["documents"]:
        nodes.append({"id": doc(d), "type": "Document", **d})
        edges.append({"from": f"patient:{mrn}", "to": doc(d), "type": "HAS_DOCUMENT"})
    for r in ab["treatment_plan_requirements"]:
        nid = f"req:{r['requirement_key']}"
        nodes.append({"id": nid, "type": "Requirement", "metric": r["metric"], "goal": f"{r['comparator']} {r['threshold']:g}",
                      "effective": [r["effective_start"], r["effective_end"]]})
        edges.append({"from": f"patient:{mrn}", "to": nid, "type": "HAS_REQUIREMENT"})
        for ev in r["evidence"]:
            edges.append({"from": nid, "to": doc(ev), "type": "STATED_IN", "passages": ev["passages"]})
    for w in ab["weeks"]:
        wid = f"week:{mrn}:{w['week_start']}"
        nodes.append({"id": wid, "type": "Week", "week_start": w["week_start"], "status": w["status"]})
        edges.append({"from": f"patient:{mrn}", "to": wid, "type": "HAS_WEEK"})
        for ev in w["evaluations"]:
            for k in ev["encounters"]:              # week lists show the short ID; encounter nodes use MRN|ID
                edges.append({"from": f"enc:{mrn}|{k}", "to": wid, "type": "COUNTED_IN"})
    for e in ab["encounters"]:
        eid = f"enc:{e['encounter_key']}"
        nodes.append({"id": eid, "type": "Encounter", **{k: e[k] for k in (
            "encounter_id", "service_date", "service_type", "disposition", "eligible", "exclusion_reason",
            "minutes_low", "minutes_high", "minutes_status", "calculation")}})
        edges.append({"from": f"patient:{mrn}", "to": eid, "type": "HAS_ENCOUNTER"})
        excluded = {c["claim_id"] for d in e["decisions"] if d["outcome"] == "evidence_excluded" for c in d["claims"]}
        for rec in e["records"]:
            edges.append({"from": eid, "to": doc(rec), "type": "DOCUMENTED_BY",
                          "record_type": rec["record_type"], "used_as_evidence": rec["claim_id"] not in excluded,
                          "passages": rec["passages"]})
        for d in e["decisions"]:
            if d["outcome"] == "field_corrected":   # claims: the corrected record and the correcting relation
                corr = [c for c in d["claims"] if c["kind"] == "relation"]
                for src in (c for c in d["claims"] if c["kind"] != "relation"):
                    for c in corr:
                        edges.append({"from": doc(c), "to": doc(src), "type": "CORRECTS", "detail": d["reason"]})
    for a in ab["assessments"]:
        aid = f"assess:{a['assessment_key']}"
        nodes.append({"id": aid, "type": "Assessment", "instrument": a["instrument"], "score": a["total_score"],
                      "completed": a["completed_date"], "form_id": a["form_id"]})
        edges.append({"from": f"patient:{mrn}", "to": aid, "type": "HAS_ASSESSMENT"})
        for ev in a["evidence"]:
            edges.append({"from": aid, "to": doc(ev), "type": "RECORDED_IN"})
        for ev in a["copies_not_counted"]:
            edges.append({"from": aid, "to": doc(ev), "type": "COPIED_IN"})
    seen, uniq = set(), []
    for e in edges:
        k = json.dumps(e, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"nodes": nodes, "edges": uniq}


def export_patient(conn, mrn: str) -> list[Path]:
    p1, p2 = safe_output_path(OUT, mrn, ".json"), safe_output_path(OUT, mrn, ".graph.json")   # before any work
    OUT.mkdir(parents=True, exist_ok=True)
    ab = build_abstraction(conn, mrn)
    p1.write_text(json.dumps(ab, indent=2, default=str))
    p2.write_text(json.dumps(build_graph(ab), indent=2, default=str))
    return [p1, p2]
