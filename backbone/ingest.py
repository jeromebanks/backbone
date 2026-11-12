"""Ingest documents: hash -> dedupe -> extract (cached) -> attribute to a patient -> verified claims.

Returns the set of patient MRNs whose evidence changed (new owners and former owners of re-extracted documents), so
only those patients are re-reconciled. A document that cannot be attributed to exactly one patient is quarantined:
its claims are stored with no patient and take part in no patient's reconciliation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import EXTRACTOR_VERSION
from .evidence import DocumentIndex
from .extract import extract_document
from .llm import DEFAULT_MODEL
from .schema import Extraction

HEADER_ID = re.compile(r"^\s*Document ID:\s*(\S+)", re.MULTILINE)
# A labelled MRN value ("MRN HG-1", "MRN: hg-1", "MRN #HG-1"); the value must contain a digit so prose isn't matched.
MRN_LABEL = re.compile(r"\bMRN\b[ \t:#]*([A-Za-z0-9-]*[0-9][A-Za-z0-9-]*)")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_mrn(mrn: str | None) -> str | None:
    if not mrn:
        return None
    return re.sub(r"\s+", "", mrn).upper()


def mrns_in_text(text: str) -> set[str]:
    """Distinct normalised MRN values labelled in the raw document text (deterministic multi-patient guard)."""
    return {norm_mrn(m.strip("-")) for m in MRN_LABEL.findall(text) if m.strip("-")}


def attribute(conn: sqlite3.Connection, text: str, ex: Extraction) -> tuple[str | None, dict | None]:
    """Decide which patient a document belongs to: (mrn, None), or (None, quarantine record).

    Never invents an identity merge: without an MRN the document must match exactly one known patient by name (and DOB
    when stated). The extraction holds one patient per document, so text naming several MRNs is not attributed at all.
    """
    labelled = sorted(mrns_in_text(text))
    if len(labelled) > 1:
        return None, {"status": "multi_patient", "candidates": labelled,
                      "reason": f"document text labels {len(labelled)} distinct MRNs; extraction holds one patient "
                                "per document, so its claims cannot be attributed"}
    mrn = norm_mrn(ex.document.patient_mrn)
    if mrn:
        return mrn, None
    name, dob = ex.document.patient_name, ex.document.patient_dob
    if not name:
        return None, {"status": "no_patient_identity", "candidates": [], "reason": "no MRN and no patient name"}
    hits = sorted(r["mrn"] for r in conn.execute(
        "SELECT mrn FROM patients WHERE name=? AND (dob=? OR ? IS NULL)", (name, dob, dob)))
    key = "name + DOB" if dob else "name (no DOB)"
    if len(hits) == 1:
        return hits[0], None
    if hits:
        return None, {"status": "ambiguous_patient", "candidates": hits,
                      "reason": f"no MRN; {key} matches {len(hits)} known patients"}
    return None, {"status": "no_patient_identity", "candidates": [],
                  "reason": f"no MRN; {key} matches no known patient"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def discover(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in {".txt", ".md"}))
        elif p.is_file():
            out.append(p)
    return out


def build_claims(sha: str, label: str, text: str, ex: Extraction, mrn: str | None) -> list[dict]:
    """Flatten one extraction into claims, verifying every quote against the document text."""
    idx = DocumentIndex(text)
    claims: list[dict] = []

    def add(kind: str, i: int, subject: str | None, payload: dict, quotes: list[str], evidence_type: str | None = None,
            supporting: list[str] = ()):
        # Every clinical claim needs at least one non-blank quote of its own, and every quote must be located.
        # Blank quotes are kept as "missing" spans (not dropped), so they fail verification and R0 rejects the
        # claim. `supporting` quotes (e.g. a break inside a session) are verified too but cannot stand in for the
        # claim's own evidence. The document claim carries no quotes and is not subject to R0.
        own = [idx.locate(q).as_dict() for q in quotes]
        spans = own + [idx.locate(q).as_dict() for q in supporting]
        grounded = kind == "document" or any((q or "").strip() for q in quotes)
        verified = int(grounded and all(s["match"] != "missing" for s in spans))
        claims.append({
            "claim_id": f"{sha[:12]}:{kind}:{i}", "sha256": sha, "doc_label": label, "patient_mrn": mrn,
            "kind": kind, "subject_key": subject, "evidence_type": evidence_type,
            "payload": json.dumps(payload, sort_keys=True), "evidence": json.dumps(spans), "verified": verified,
        })

    doc = ex.document.model_dump()
    rels = doc.pop("relations")
    add("document", 0, label, doc, [])
    for i, r in enumerate(rels):
        add("relation", i, r.get("encounter_id") or r.get("form_id"), r, [r["quote"]])
    for i, ev in enumerate(ex.service_events):
        d = ev.model_dump()
        add("service_event", i, ev.encounter_id, d, list(ev.quotes), ev.evidence_type,
            supporting=[n.quote for n in ev.nontherapeutic_intervals])
    for i, a in enumerate(ex.assessments):
        add("assessment", i, a.form_id or f"{a.instrument}@{a.completed_date}", a.model_dump(), [a.quote])
    for i, o in enumerate(ex.observations):
        add("observation", i, o.date, o.model_dump(), [o.quote])
    for i, p in enumerate(ex.plan_requirements):
        add("plan_requirement", i, label, p.model_dump(), [p.quote])
    return claims


def ingest(conn: sqlite3.Connection, paths: list[str | Path], *, model: str = DEFAULT_MODEL,
           effort: str = "high", workers: int | None = None, log=print) -> dict:
    """Ingest files. Idempotent: byte-identical files are recorded once; cached extractions are reused."""
    t0 = time.monotonic()
    files = discover(paths)
    workers = workers or int(os.environ.get("BACKBONE_CONCURRENCY", "6"))
    todo: dict[str, tuple[Path, str]] = {}
    stats = {"files": len(files), "new_documents": 0, "duplicate_files": 0, "extracted_llm": 0,
             "extracted_cache": 0, "already_ingested": 0, "failed": [], "affected_patients": set(), "quarantined": [],
             "llm_cost_usd": 0.0, "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_latency_ms": []}

    for f in files:
        raw = f.read_bytes()
        sha = sha256_bytes(raw)
        text = raw.decode("utf-8", errors="replace")
        row = conn.execute("SELECT paths FROM documents WHERE sha256=?", (sha,)).fetchone()
        if row:
            known = json.loads(row["paths"])
            if str(f) not in known:
                known.append(str(f))
                conn.execute("UPDATE documents SET paths=? WHERE sha256=?", (json.dumps(known), sha))
                stats["duplicate_files"] += 1
            have = conn.execute("SELECT 1 FROM extractions WHERE sha256=? AND extractor_version=? AND model=?",
                                (sha, EXTRACTOR_VERSION, model)).fetchone()
            if have:
                stats["already_ingested"] += 1
                continue
        elif sha in todo:
            stats["duplicate_files"] += 1
            continue
        else:
            m = HEADER_ID.search(text)
            label = m.group(1) if m else f.stem
            conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) "
                         "VALUES (?,?,?,?,?,?)", (sha, label, json.dumps([str(f)]), text, None, _now()))
            stats["new_documents"] += 1
        todo[sha] = (f, text)
    conn.commit()

    def work(sha: str):
        f, text = todo[sha]
        return sha, *extract_document(sha, f.name, text, model=model, effort=effort)

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(work, sha): sha for sha in todo}
        for fut in as_completed(futs):
            sha = futs[fut]
            try:
                results.append(fut.result())
                _, _, meta = results[-1]
                src = "cache" if meta.get("from_cache") else f"LLM {(meta.get('latency_ms') or 0)/1000:.1f}s"
                log(f"  extracted {todo[sha][0].name} ({src})")
            except Exception as e:  # one bad document must not sink the run
                stats["failed"].append({"file": str(todo[sha][0]), "error": str(e)[:300]})
                log(f"  FAILED {todo[sha][0].name}: {str(e)[:200]}")

    # Documents carrying an MRN first, so a name-only document in the same batch can match a patient they create.
    for sha, ex, meta in sorted(results, key=lambda r: (norm_mrn(r[1].document.patient_mrn) is None, r[0])):
        label = conn.execute("SELECT doc_label FROM documents WHERE sha256=?", (sha,)).fetchone()["doc_label"]
        text = todo[sha][1]
        # Former owners of this document's evidence (re-extraction may move or quarantine it): they must be
        # re-reconciled too, or they keep derived rows built from claims that no longer belong to them.
        former = {r[0] for r in conn.execute(
            "SELECT DISTINCT patient_mrn FROM claims WHERE sha256=? AND patient_mrn IS NOT NULL", (sha,))}
        former |= {r[0] for r in conn.execute(
            "SELECT patient_mrn FROM documents WHERE sha256=? AND patient_mrn IS NOT NULL", (sha,))}
        stats["affected_patients"] |= former
        mrn, quarantine = attribute(conn, text, ex)
        conn.execute("UPDATE documents SET patient_mrn=? WHERE sha256=?", (mrn, sha))
        conn.execute("DELETE FROM quarantine WHERE sha256=?", (sha,))
        if quarantine:
            conn.execute("INSERT INTO quarantine VALUES (?,?,?,?,?,?)",
                         (sha, label, quarantine["status"], quarantine["reason"],
                          json.dumps(quarantine["candidates"]), _now()))
            stats["quarantined"].append({"file": str(todo[sha][0]), "doc_label": label, **quarantine})
            log(f"  QUARANTINED {todo[sha][0].name}: {quarantine['reason']}")
        conn.execute("DELETE FROM claims WHERE sha256=?", (sha,))
        for c in build_claims(sha, label, text, ex, mrn):
            conn.execute("INSERT INTO claims VALUES (:claim_id,:sha256,:doc_label,:patient_mrn,:kind,:subject_key,"
                         ":evidence_type,:payload,:evidence,:verified)", c)
        conn.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (sha, EXTRACTOR_VERSION, model, json.dumps(ex.model_dump()), meta.get("latency_ms"),
                      meta.get("input_tokens"), meta.get("output_tokens"), meta.get("cost_usd"),
                      int(bool(meta.get("from_cache"))), _now()))
        if mrn:
            if not conn.execute("SELECT 1 FROM patients WHERE mrn=?", (mrn,)).fetchone():
                conn.execute("INSERT INTO patients(mrn, name, dob) VALUES (?,?,?)",
                             (mrn, ex.document.patient_name, ex.document.patient_dob))
            stats["affected_patients"].add(mrn)
        if meta.get("from_cache"):
            stats["extracted_cache"] += 1
        else:
            stats["extracted_llm"] += 1
            stats["llm_cost_usd"] += meta.get("cost_usd") or 0.0
            stats["llm_input_tokens"] += meta.get("input_tokens") or 0
            stats["llm_output_tokens"] += meta.get("output_tokens") or 0
            stats["llm_latency_ms"].append(meta.get("latency_ms") or 0)
    conn.commit()
    stats["affected_patients"] = sorted(stats["affected_patients"])
    stats["quarantined"].sort(key=lambda q: q["file"])
    stats["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return stats
