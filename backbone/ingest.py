"""Ingest documents: hash -> dedupe -> extract (cached) -> verified claims.

Returns the set of patient MRNs whose evidence changed, so only those patients are re-reconciled.
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


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_mrn(mrn: str | None) -> str | None:
    if not mrn:
        return None
    return re.sub(r"\s+", "", mrn).upper()


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

    def add(kind: str, i: int, subject: str | None, payload: dict, quotes: list[str], evidence_type: str | None = None):
        spans = [idx.locate(q).as_dict() for q in quotes if q]
        verified = int(all(s["match"] != "missing" for s in spans))
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
        quotes = list(ev.quotes) + [n.quote for n in ev.nontherapeutic_intervals]
        add("service_event", i, ev.encounter_id, d, quotes, ev.evidence_type)
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
             "extracted_cache": 0, "already_ingested": 0, "failed": [], "affected_patients": set(),
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
                src = "cache" if meta.get("from_cache") else f"LLM {meta['latency_ms']/1000:.1f}s"
                log(f"  extracted {todo[sha][0].name} ({src})")
            except Exception as e:  # one bad document must not sink the run
                stats["failed"].append({"file": str(todo[sha][0]), "error": str(e)[:300]})
                log(f"  FAILED {todo[sha][0].name}: {str(e)[:200]}")

    for sha, ex, meta in sorted(results, key=lambda r: r[0]):
        label = conn.execute("SELECT doc_label FROM documents WHERE sha256=?", (sha,)).fetchone()["doc_label"]
        text = todo[sha][1]
        mrn = norm_mrn(ex.document.patient_mrn)
        if mrn is None and ex.document.patient_name:
            hit = conn.execute("SELECT mrn FROM patients WHERE name=? AND (dob=? OR ? IS NULL)",
                               (ex.document.patient_name, ex.document.patient_dob, ex.document.patient_dob)).fetchone()
            mrn = hit["mrn"] if hit else None
        mrn = mrn or "UNRESOLVED"
        conn.execute("UPDATE documents SET patient_mrn=? WHERE sha256=?", (mrn, sha))
        conn.execute("DELETE FROM claims WHERE sha256=?", (sha,))
        for c in build_claims(sha, label, text, ex, mrn):
            conn.execute("INSERT INTO claims VALUES (:claim_id,:sha256,:doc_label,:patient_mrn,:kind,:subject_key,"
                         ":evidence_type,:payload,:evidence,:verified)", c)
        conn.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (sha, EXTRACTOR_VERSION, model, json.dumps(ex.model_dump()), meta.get("latency_ms"),
                      meta.get("input_tokens"), meta.get("output_tokens"), meta.get("cost_usd"),
                      int(bool(meta.get("from_cache"))), _now()))
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
    stats["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return stats
