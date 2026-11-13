"""Measured benchmarks -> out/benchmarks.json and out/benchmarks.md.

Everything here is measured on this machine. The synthetic scale test clones the reconciled clinical layer of the
real patient N times (no claims, no documents) to time the query layer at collection scale; it is labelled
synthetic and says nothing about extraction cost, which is reported from the real extraction run.
"""
from __future__ import annotations

import json
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path

from .db import ROOT, connect, connect_readonly
from .extract import CACHE_DIR
from .ingest import ingest
from .query import CareStep, ComplianceStep, QueryPlan, Scope, TimelineStep, execute_plan
from .reconcile import reconcile_patients

OUT = ROOT / "out"
DOCS = ROOT / "documents"


def _timeit(fn, n=20):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return {"runs": n, "median_ms": round(statistics.median(ts), 3), "p95_ms": round(ts[int(0.95 * (n - 1))], 3),
            "min_ms": round(ts[0], 3)}


def _plan(*steps):
    return QueryPlan(question="bench", steps=list(steps))


def _patient_plans(mrn, start="2026-01-05", end="2026-01-30"):
    sc = dict(patients=[mrn], start=start, end=end)
    return {
        "care_by_week": _plan(CareStep(scope=Scope(**sc, include_evidence=False), group_by="week")),
        "care_with_exclusions_and_evidence": _plan(CareStep(scope=Scope(**sc, include_excluded=True), group_by="service_type")),
        "weekly_compliance": _plan(ComplianceStep(scope=Scope(**sc, include_evidence=False), consecutive_below=2)),
        "reconstruct_day": _plan(TimelineStep(scope=Scope(patients=[mrn], start="2026-01-19", end="2026-01-19",
                                                          include_excluded=True), kinds=["encounters", "documents", "decisions"])),
        "symptom_course": _plan(TimelineStep(scope=Scope(**sc), kinds=["assessments", "observations"])),
    }


def _extraction_stats():
    metas = [json.loads(p.read_text())["meta"] for p in CACHE_DIR.glob("*.json")]
    lat = [m["latency_ms"] for m in metas]
    return {
        "documents": len(metas), "model": sorted({m["model"] for m in metas}), "effort": sorted({m["effort"] for m in metas}),
        "latency_ms_mean": int(statistics.mean(lat)), "latency_ms_p95": int(sorted(lat)[int(0.95 * (len(lat) - 1))]),
        "input_tokens_total": sum(m["input_tokens"] for m in metas),
        "output_tokens_total": sum(m["output_tokens"] for m in metas),
        "input_tokens_per_doc": int(statistics.mean(m["input_tokens"] for m in metas)),
        "output_tokens_per_doc": int(statistics.mean(m["output_tokens"] for m in metas)),
        "list_price_cost_usd_total": round(sum(m["cost_usd"] or 0 for m in metas), 3),
        "list_price_cost_usd_per_doc": round(statistics.mean(m["cost_usd"] or 0 for m in metas), 4),
        "note": "cost is the API list-price equivalent reported by the CLI; the run used a Claude subscription",
    }


def _clone(src_db: Path, dst_db: Path, n: int) -> None:
    src = connect_readonly(src_db)
    dst = connect(dst_db)
    encs = [dict(r) for r in src.execute("SELECT * FROM encounters WHERE mrn='HG-M042'")]
    reqs = [dict(r) for r in src.execute("SELECT * FROM plan_requirements WHERE mrn='HG-M042'")]
    with dst:
        for i in range(n):
            m = f"SYN-{i:06d}"
            dst.execute("INSERT INTO patients(mrn, name) VALUES (?,?)", (m, f"Synthetic {i}"))
            dst.executemany(f"INSERT INTO encounters({','.join(encs[0])}) VALUES ({','.join('?' * len(encs[0]))})",
                            [list({**e, "mrn": m, "encounter_key": e["encounter_key"].replace("HG-M042", m)}.values()) for e in encs])
            dst.executemany(f"INSERT INTO plan_requirements({','.join(reqs[0])}) VALUES ({','.join('?' * len(reqs[0]))})",
                            [list({**r, "mrn": m, "requirement_key": r["requirement_key"].replace("HG-M042", m)}.values()) for r in reqs])


def cached_repeat(db_path, question: str, n: int = 5) -> dict:
    """Latency of answering a question whose answer is already cached (#82). Runs on a temporary copy of the DB with
    LLM calls blocked: if no valid cached answer exists for the current abstraction (any version or fingerprint
    change empties the cache, and failing answers are never cached), the step is skipped instead of calling the LLM
    or writing the tracked database."""
    import shutil
    from . import answer as A
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "bench.db"
        shutil.copyfile(db_path, copy)
        real = A.complete_json

        def blocked(*a, **k):
            raise RuntimeError("benchmark must not call the LLM")
        A.complete_json = blocked
        try:
            return _timeit(lambda: A.answer_question(question, db_path=copy), n=n)
        except RuntimeError as e:
            if "must not call the LLM" not in str(e):
                raise
            return {"skipped": "no valid cached answer for the current abstraction; measuring it would need LLM calls"}
        finally:
            A.complete_json = real


def run_benchmarks(db_path, synthetic_patients: int = 10000) -> dict:
    res: dict = {"machine": f"{platform.system()} {platform.machine()} / Python {platform.python_version()}",
                 "measured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    res["extraction_initial_run"] = _extraction_stats()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 1. rebuild everything from the extraction cache (what a restart / fresh checkout does)
        conn = connect(td / "rebuild.db")
        t0 = time.perf_counter()
        st = ingest(conn, [DOCS], log=lambda *a: None)
        t1 = time.perf_counter()
        rec = reconcile_patients(conn, st["affected_patients"])
        t2 = time.perf_counter()
        res["rebuild_from_cache"] = {"documents": st["files"], "llm_calls": st["extracted_llm"],
                                     "ingest_ms": round((t1 - t0) * 1000, 1), "reconcile_ms": round((t2 - t1) * 1000, 1),
                                     "reconcile": rec}
        # 2. re-ingest unchanged corpus
        t0 = time.perf_counter()
        st2 = ingest(conn, [DOCS], log=lambda *a: None)
        res["reingest_unchanged"] = {"ms": round((time.perf_counter() - t0) * 1000, 1), "llm_calls": st2["extracted_llm"],
                                     "new_documents": st2["new_documents"], "patients_reconciled": len(st2["affected_patients"])}
        # 3. incremental: corpus minus one document, then add it
        conn3 = connect(td / "incr.db")
        files = sorted(DOCS.glob("*.txt"))
        ingest(conn3, files[:-1], log=lambda *a: None)
        reconcile_patients(conn3, ["HG-M042"])
        t0 = time.perf_counter()
        st3 = ingest(conn3, [files[-1]], log=lambda *a: None)
        t1 = time.perf_counter()
        reconcile_patients(conn3, st3["affected_patients"])
        res["incremental_add_one_document"] = {
            "document": files[-1].name, "ingest_ms_excluding_llm": round((t1 - t0) * 1000, 1),
            "reconcile_one_patient_ms": round((time.perf_counter() - t1) * 1000, 1),
            "llm_calls_if_new": 1, "llm_latency_ms_if_new": res["extraction_initial_run"]["latency_ms_mean"]}
        # 4. per-patient operator latency on the real abstraction
        ro = connect_readonly(td / "rebuild.db")
        res["operator_latency_real_patient"] = {k: _timeit(lambda p=p: execute_plan(ro, p))
                                                for k, p in _patient_plans("HG-M042").items()}
        # 5. synthetic collection scale (query layer only)
        syn = td / "syn.db"
        t0 = time.perf_counter()
        _clone(td / "rebuild.db", syn, synthetic_patients)
        clone_ms = (time.perf_counter() - t0) * 1000
        sc = connect_readonly(syn)
        n_enc = sc.execute("SELECT COUNT(*) FROM encounters").fetchone()[0]
        allsc = dict(patients="all", start="2026-01-05", end="2026-01-30", include_evidence=False)
        res["synthetic_collection_scale"] = {
            "label": "SYNTHETIC: reconciled layer of the real patient cloned per patient; documents/claims not cloned",
            "patients": synthetic_patients, "encounters": n_enc, "build_ms": round(clone_ms, 1),
            "db_mb": round(os.path.getsize(syn) / 1e6, 1),
            "single_patient_care_by_week": _timeit(lambda: execute_plan(sc, _patient_plans("SYN-000123")["care_by_week"])),
            "single_patient_weekly_compliance": _timeit(lambda: execute_plan(sc, _patient_plans("SYN-000123")["weekly_compliance"])),
            "collection_care_by_patient": _timeit(lambda: execute_plan(sc, _plan(CareStep(scope=Scope(**allsc), group_by="patient"))), n=3),
            "collection_care_by_week": _timeit(lambda: execute_plan(sc, _plan(CareStep(scope=Scope(**allsc), group_by="week"))), n=3),
            "collection_weekly_compliance_consecutive_below_2": _timeit(
                lambda: execute_plan(sc, _plan(ComplianceStep(scope=Scope(**allsc), consecutive_below=2))), n=1),
        }
    # 6. persisted abstraction size
    main = connect_readonly(db_path)
    res["persisted_abstraction"] = {
        "db_path": str(Path(db_path).relative_to(ROOT)) if str(db_path).startswith(str(ROOT)) else str(db_path),
        "db_bytes": os.path.getsize(db_path),
        "extraction_cache_bytes": sum(p.stat().st_size for p in CACHE_DIR.glob("*.json")),
        **{t: main.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
           for t in ("documents", "claims", "encounters", "decisions", "conflicts", "assessments", "observations")},
        "unverified_claims": main.execute("SELECT COUNT(*) FROM claims WHERE verified=0").fetchone()[0],
    }
    # 7. question answering latency (from the recorded answer runs)
    ans = {}
    for p in sorted((OUT / "answers").glob("DEV-*.json")):
        a = json.loads(p.read_text())
        ans[a["id"]] = {"timings_ms": a.get("timings_ms_original") or a["timings_ms"], "llm": a.get("llm"),
                        "postcheck_ok": a["postcheck"]["ok"]}
    res["question_answering"] = ans
    if ans:
        q = json.loads((ROOT / "questions.json").read_text())[0]["question"]
        res["question_answering_cached_repeat"] = cached_repeat(db_path, q)
    OUT.mkdir(exist_ok=True)
    (OUT / "benchmarks.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
    return res
