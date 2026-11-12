"""Compact, human/agent-readable rendering of a QueryPlan's results envelope.

Used by `python -m backbone plan --summary` so an agent (e.g. the Claude Code `clinical-qa` skill) can read computed
facts, calculations, conflicts, exclusions and citable evidence without loading the full JSON.
"""
from __future__ import annotations


def _b(x) -> str:
    if isinstance(x, dict) and "low" in x:
        lo, hi = x["low"], x["high"]
        return f"{lo}" if lo == hi else f"{lo}–{'∞' if hi is None else hi}"
    return str(x)


def _clip(s: str, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def summarize(res: dict, *, max_rows: int = 40, max_evidence: int = 60) -> str:
    out: list[str] = []
    if res.get("unsupported"):
        return f"UNSUPPORTED: {res['unsupported']}"
    for i, r in enumerate(res.get("results", []), 1):
        sc = r["params"]["scope"]
        out.append(f"## Step {i}: {r['op']}  patients={sc['patients']}  {sc['start']}..{sc['end']}"
                   + (f"  types={sc['service_types']}" if sc.get("service_types") else ""))
        t = r.get("totals") or {}
        tparts = [f"{k}={_b(v)}" for k, v in t.items() if isinstance(v, dict) and "low" in v]
        if tparts:
            out.append("TOTALS: " + ", ".join(tparts))
        for bt in t.get("by_service_type", []) or []:
            out.append(f"  by type {bt['service_type']}: sessions={_b(bt['sessions'])} days={_b(bt['therapy_days'])} minutes={_b(bt['minutes'])}")
        for k in ("weeks_by_status", "patients_by_run_status"):
            if k in t:
                out.append(f"{k.upper()}: {t[k]}")
        for c in r.get("calculation", [])[:max_rows]:
            out.append(f"CALC: {_clip(c, 400)}")
        groups = r.get("groups", [])
        for g in groups[:max_rows]:
            if r["op"] == "compliance":
                ev = (g.get("evaluations") or [{}])[0]
                tt = ev.get("totals", {})
                reqs = "; ".join(f"{q['metric']} {q['goal']} → {q['status']}" for q in ev.get("requirements", []))
                out.append(f"WEEK {g['week_start']} [{g['status']}] days={_b(tt.get('therapy_days', {}))} "
                           f"minutes={_b(tt.get('minutes', {}))} ({ev.get('minutes_calculation', '')}) | {reqs}"
                           + (f" | notes: {'; '.join(g['notes'])}" if g.get("notes") else ""))
            elif r["op"] == "compare":
                out.append(f"{g['side'].upper()} {g['period']} ({g['weeks']} wk): sessions={_b(g['sessions'])} "
                           f"minutes={_b(g['minutes'])} per_week={_b(g['minutes_per_week'])} "
                           f"by_type={ {k: _b(v['minutes']) for k, v in g['by_service_type'].items()} }")
            else:
                out.append(f"GROUP {g.get('group')}: sessions={_b(g.get('sessions', {}))} "
                           f"days={_b(g.get('therapy_days', {}))} minutes={_b(g.get('minutes', {}))}"
                           + (f" ({g['minutes_calculation']})" if g.get("minutes_calculation") else ""))
        if len(groups) > max_rows:
            out.append(f"… {len(groups) - max_rows} more groups")
        facts = r.get("facts", [])
        for f in facts[:max_rows]:
            k = f.get("kind")
            if k == "assessment":
                out.append(f"ASSESSMENT {f['date']} {f['instrument']}={f['total_score']} form={f['form_id']} "
                           f"items={f['item_scores']} in={f['recorded_in']} copies_not_counted={f['copies_not_counted']}")
            elif k == "observation":
                out.append(f"OBS {f['date']} [{f['domain']}/{f['source']}] {_clip(f['statement'])} {f['documents']}")
            elif k == "document":
                a = "; ".join(f"{x['encounter']} {x['record_type']} disp={x['disposition']} arr={x['arrival']} "
                              f"dep={x['departure']} contact={x['contact_intervals']} nontherapeutic={x['nontherapeutic']} "
                              f"stated={x['stated_minutes']}" for x in f["assertions"])
                rel = f" relations={f['relations']}" if f.get("relations") else ""
                out.append(f"DOC {f['doc_id']} ({_clip(f.get('title') or '', 70)}; signed {f.get('signed_at')}; "
                           f"received {f.get('received_at')}; {f.get('finality')}): {a}{rel}")
            elif "encounter" in f:
                m = f.get("patient_present_minutes")
                out.append(f"ENCOUNTER {f['encounter']} {f['date']} {f['service_type']} {f['disposition']} "
                           f"counts={f['counts_as_therapy_session']} minutes={_b(m) if m else '-'}"
                           + (f" reason={f['exclusion_reason']}" if f.get("exclusion_reason") else "")
                           + f" records={f['records']}" + (f" flags={f['flags']}" if f.get("flags") else ""))
            elif "status" in f and "patient" in f:
                out.append(f"RUNS {f['patient']}: {f['status']} definite={f.get('definite_runs')} possible={f.get('possible_runs')}")
        if len(facts) > max_rows:
            out.append(f"… {len(facts) - max_rows} more facts")
        for x in r.get("exclusions", [])[:max_rows]:
            out.append(f"EXCLUDED {x['encounter']} {x['date']} {x['service_type']}: {x['reason']}"
                       + (f" records={x['records']}" if x.get("records") else ""))
        for c in r.get("conflicts", []):
            cands = " vs ".join(f"{k.get('value')}" + (f" ({k.get('minutes')} min)" if k.get("minutes") is not None else "")
                                + f" {k.get('documents', [])}" for k in c["candidates"])
            out.append(f"CONFLICT {c['subject']} {c['field']} [{c['resolution']}]: {cands}")
        for d in r.get("decisions", [])[:max_rows]:
            if d["rule"] in ("R2", "R3", "R4", "R7", "R8", "R9") or d["outcome"].startswith("minutes_"):
                out.append(f"DECISION {d['subject']} {d['rule']} {d['outcome']}: {_clip(d['reason'], 260)}")
        for n in r.get("notes", []):
            out.append(f"NOTE: {n}")
        ev = r.get("evidence", [])
        for e in ev[:max_evidence]:
            for p in e["passages"]:
                out.append(f"EVIDENCE ({e['doc_id']} L{p['lines']}) [{e['record_type']}] \"{_clip(p['quote'], 180)}\"")
        if len(ev) > max_evidence:
            out.append(f"… {len(ev) - max_evidence} more evidence records (see --out JSON)")
        out.append("")
    return "\n".join(out)
