"""Command line interface.

  python -m backbone ingest documents/            # hash, extract (cached), claims, reconcile affected patients
  python -m backbone reconcile [--patient MRN]    # rebuild the clinical layer from claims (no LLM)
  python -m backbone ask "question"               # question -> QueryPlan -> deterministic results -> cited answer
  python -m backbone answer questions.json        # answer a question file into out/answers/
  python -m backbone plan plan.json               # execute a hand-written QueryPlan (no LLM at all)
  python -m backbone verify-answers               # re-execute saved answers' plans (no LLM); results must match
  python -m backbone export --patient HG-M042     # patient abstraction JSON + graph JSON
  python -m backbone benchmark                    # measured timings -> out/benchmarks.json
  python -m backbone stats
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from .db import DEFAULT_DB, connect


def _log_run(conn, command: str, t0: float, details: dict):
    conn.execute("INSERT INTO run_log(command, started_at, duration_ms, details) VALUES (?,?,?,?)",
                 (command, datetime.now().isoformat(timespec="seconds"), int((time.monotonic() - t0) * 1000),
                  json.dumps(details, default=str)))
    conn.commit()


def cmd_ingest(args):
    from .ingest import ingest
    from .reconcile import reconcile_patients
    conn = connect(args.db)
    t0 = time.monotonic()
    stats = ingest(conn, args.paths, effort=args.effort, workers=args.workers)
    rec = reconcile_patients(conn, stats["affected_patients"]) if stats["affected_patients"] else {}
    stats["reconcile"] = rec
    _log_run(conn, "ingest " + " ".join(args.paths), t0, stats)
    lat = stats.pop("llm_latency_ms")
    if lat:
        stats["llm_latency_ms_mean"] = int(sum(lat) / len(lat))
    print(json.dumps(stats, indent=2, default=str))


def cmd_reconcile(args):
    from .reconcile import reconcile_patients
    conn = connect(args.db)
    t0 = time.monotonic()
    mrns = [args.patient] if args.patient else [r["mrn"] for r in conn.execute("SELECT mrn FROM patients")]
    rec = reconcile_patients(conn, mrns)
    _log_run(conn, "reconcile", t0, rec)
    print(json.dumps(rec, indent=2, default=str))


def cmd_stats(args):
    conn = connect(args.db)
    out = {}
    for t in ["documents", "extractions", "claims", "patients", "encounters", "encounter_intervals",
              "plan_requirements", "assessments", "observations", "decisions", "conflicts"]:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    out["unverified_claims"] = conn.execute("SELECT COUNT(*) FROM claims WHERE verified=0").fetchone()[0]
    print(json.dumps(out, indent=2))


def cmd_ask(args):
    from .answer import answer_question
    res = answer_question(args.question, db_path=args.db, use_cache=not args.no_cache)
    print(res["answer_markdown"])
    if args.json:
        print(json.dumps(res, indent=2, default=str))


def cmd_answer(args):
    from .answer import answer_file
    answer_file(args.file, db_path=args.db, use_cache=not args.no_cache)


def cmd_verify(args):
    from .answer import verify_answers
    rep = verify_answers(db_path=args.db)
    for r in rep:
        print(f"{r['id']}: results identical={r['results_identical']} postcheck_ok={r['postcheck_ok']}"
              + ("" if r["postcheck_ok"] else f"  {r['postcheck']}"))
    if not all(r["results_identical"] for r in rep):
        sys.exit(1)


def cmd_plan(args):
    from .query import QueryPlan, execute_plan
    from .db import connect_readonly
    plan = QueryPlan.model_validate_json(open(args.file).read())
    print(plan.explain())
    print(json.dumps(execute_plan(connect_readonly(args.db), plan), indent=2, default=str))


def cmd_export(args):
    from .export import export_patient
    conn = connect(args.db)
    for p in export_patient(conn, args.patient):
        print(p)


def cmd_benchmark(args):
    from .bench import run_benchmarks
    run_benchmarks(args.db, synthetic_patients=args.synthetic_patients)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="backbone")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest"); p.add_argument("paths", nargs="+")
    p.add_argument("--effort", default="high"); p.add_argument("--workers", type=int, default=None)
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("reconcile"); p.add_argument("--patient"); p.set_defaults(fn=cmd_reconcile)
    p = sub.add_parser("stats"); p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("ask"); p.add_argument("question"); p.add_argument("--json", action="store_true")
    p.add_argument("--no-cache", action="store_true"); p.set_defaults(fn=cmd_ask)
    p = sub.add_parser("answer"); p.add_argument("file"); p.add_argument("--no-cache", action="store_true")
    p.set_defaults(fn=cmd_answer)
    p = sub.add_parser("plan"); p.add_argument("file"); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("verify-answers"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("export"); p.add_argument("--patient", required=True); p.set_defaults(fn=cmd_export)
    p = sub.add_parser("benchmark"); p.add_argument("--synthetic-patients", type=int, default=10000)
    p.set_defaults(fn=cmd_benchmark)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
