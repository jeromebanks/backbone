"""The four domain operators. Thin by design: they select from the reconciled abstraction and call project.py;
no clinical rule is implemented here. Every operator returns the same machine-readable envelope:

  {op, params, totals, groups, facts, calculation, exclusions, conflicts, decisions, evidence, notes, sql}
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from .project import (SqlLog, aggregate, consecutive_runs, group_key, patients_in_scope, plan_change_dates,
                      plan_requirements, select_encounters, weekly_compliance)
from .query import CareStep, ComplianceStep, CompareStep, Scope, TimelineStep


def _short(key: str) -> str:
    return key.split("|", 1)[1] if "|" in key else key


def _envelope(step, log: SqlLog, **kw) -> dict:
    env = {"op": step.op, "params": step.model_dump(mode="json", exclude={"op"}), "totals": {}, "groups": [],
           "facts": [], "calculation": [], "exclusions": [], "conflicts": [], "decisions": [], "evidence": [],
           "notes": []}
    env.update(kw)
    env["sql"] = log.statements
    return env


# --------------------------------------------------------------------------------------------- shared helpers

def _evidence(conn, claim_ids: list[str], log: SqlLog) -> list[dict]:
    if not claim_ids:
        return []
    ids = sorted(set(claim_ids))
    rows = log.run(conn, f"SELECT c.claim_id, c.doc_label, c.kind, c.evidence_type, c.evidence, d.paths "
                         f"FROM claims c JOIN documents d ON d.sha256 = c.sha256 "
                         f"WHERE c.claim_id IN ({','.join('?' * len(ids))}) ORDER BY c.doc_label, c.claim_id", ids)
    out = []
    for r in rows:
        spans = [s for s in json.loads(r["evidence"]) if s["line_start"]]
        if not spans:
            continue
        out.append({"claim_id": r["claim_id"], "doc_id": r["doc_label"],
                    "file": json.loads(r["paths"])[0].split("/")[-1], "record_type": r["evidence_type"] or r["kind"],
                    "passages": [{"lines": f"{s['line_start']}-{s['line_end']}" if s["line_end"] != s["line_start"]
                                  else str(s["line_start"]), "quote": s["quote"]} for s in spans]})
    return out


def _decisions(conn, mrn_keys: list[str], log: SqlLog, rules: tuple | None = None) -> list[dict]:
    if not mrn_keys:
        return []
    sql = (f"SELECT subject_key, rule, outcome, reason FROM decisions WHERE subject_key IN "
           f"({','.join('?' * len(mrn_keys))})")
    params = list(mrn_keys)
    if rules:
        sql += f" AND rule IN ({','.join('?' * len(rules))})"
        params += list(rules)
    sql += " ORDER BY subject_key, decision_id"
    return [{"subject": _short(r["subject_key"]), "rule": r["rule"], "outcome": r["outcome"], "reason": r["reason"]}
            for r in log.run(conn, sql, params)]


def _conflicts(conn, keys: list[str], log: SqlLog) -> list[dict]:
    if not keys:
        return []
    rows = log.run(conn, f"SELECT subject_key, field, candidates, resolution FROM conflicts WHERE subject_key IN "
                         f"({','.join('?' * len(keys))}) ORDER BY subject_key, conflict_id", keys)
    out = []
    for r in rows:
        cands = json.loads(r["candidates"])
        docs = {}
        for c in cands:
            ids = c.get("claim_ids", [])
            if ids:
                lab = log.run(conn, f"SELECT DISTINCT doc_label FROM claims WHERE claim_id IN ({','.join('?' * len(ids))})", ids)
                c["documents"] = sorted(x["doc_label"] for x in lab)
        out.append({"subject": _short(r["subject_key"]), "field": r["field"], "resolution": r["resolution"],
                    "candidates": cands})
    return out


def _docs_of(conn, claim_ids: list[str], log: SqlLog) -> list[str]:
    if not claim_ids:
        return []
    rows = log.run(conn, f"SELECT DISTINCT doc_label FROM claims WHERE claim_id IN ({','.join('?' * len(claim_ids))})",
                   claim_ids)
    return sorted(r["doc_label"] for r in rows)


def _enc_fact(conn, e: dict, log: SqlLog) -> dict:
    return {"encounter": _short(e["encounter_key"]), "patient": e["mrn"], "date": e["service_date"],
            "week_start": e["week_start"], "service_type": e["service_type"], "modality": e["modality"],
            "disposition": e["disposition"], "counts_as_therapy_session": e["eligible"],
            "exclusion_reason": e["exclusion_reason"],
            "patient_present_minutes": None if e["minutes_status"] == "not_applicable" and e["minutes_low"] is None
            else {"low": e["minutes_low"], "high": e["minutes_high"], "status": e["minutes_status"]},
            "calculation": e["calculation"], "records": _docs_of(conn, e["claim_ids"], log), "flags": e["flags"]}


DETAIL_LIMIT = 200   # per-encounter detail rows returned by collection-scale queries (totals are always complete)


def _cap(items: list, notes: list, what: str) -> list:
    if len(items) > DETAIL_LIMIT:
        notes.append(f"{what}: showing {DETAIL_LIMIT} of {len(items)} rows; totals and groups cover all rows")
        return items[:DETAIL_LIMIT]
    return items


def _ids(encs: list[dict], n: int = 60) -> str:
    s = ", ".join(_short(e["encounter_key"]) for e in encs[:n])
    return s + (f", … (+{len(encs) - n} more)" if len(encs) > n else "")


def _minutes_expr(encs: list[dict], n: int = 60) -> str:
    if len(encs) > n:
        return f"sum over {len(encs)} encounters (first {n}: " + _minutes_expr(encs[:n]) + " …)"
    parts = []
    for e in encs:
        if e["eligible"] == "no":
            continue
        lo, hi = e["minutes_low"], e["minutes_high"]
        lo_s = "0" if e["eligible"] == "uncertain" or lo is None else f"{lo:g}"
        v = f"{lo:g}" if lo == hi and lo is not None else f"[{lo_s}–{'?' if hi is None else f'{hi:g}'}]"
        parts.append(f"{v} ({_short(e['encounter_key'])})")
    return " + ".join(parts) or "0"


def _fmt_bound(b: dict) -> str:
    return f"{b['low']}" if b["low"] == b["high"] else f"{b['low']}–{'∞' if b['high'] is None else b['high']}"


# --------------------------------------------------------------------------------------------- operators

def care(conn, step: CareStep) -> dict:
    log, sc = SqlLog(), step.scope
    encs_all = select_encounters(conn, sc, log, include_excluded=True)
    encs = [e for e in encs_all if e["eligible"] != "no"]
    totals = aggregate(encs)
    notes: list[str] = []
    buckets: dict[str, list] = defaultdict(list)            # one pass: O(n), not O(groups × n)
    types: dict[str, list] = defaultdict(list)
    for e in encs:
        types[e["service_type"]].append(e)
        if step.group_by != "none":
            buckets[group_key(e, step.group_by)].append(e)
    groups = [{"group": k, **aggregate(g), "encounters": [_short(e["encounter_key"]) for e in g],
               "minutes_calculation": _minutes_expr(g)} for k, g in sorted(buckets.items())]
    by_type = [{"service_type": t, **{k: v for k, v in aggregate(g).items() if k in ("sessions", "therapy_days", "minutes")}}
               for t, g in sorted(types.items())]
    calc = [
        f"sessions = count of encounters that count as therapy sessions = {_fmt_bound(totals['sessions'])}: {_ids(encs)}",
        f"therapy days = distinct (patient, date) pairs among them = {_fmt_bound(totals['therapy_days'])}"
        + (": " + ", ".join(sorted({e['service_date'] for e in encs})) if len(encs) <= 60 else ""),
        f"patient-present minutes = {_minutes_expr(encs)} = {_fmt_bound(totals['minutes'])} min "
        f"({_fmt_bound(totals['hours'])} h)",
    ]
    shown = _cap(encs_all if sc.include_excluded else encs, notes, "facts")
    excluded = _cap([e for e in encs_all if e["eligible"] == "no"], notes, "exclusions")
    shown_keys = [e["encounter_key"] for e in shown]
    env = _envelope(
        step, log,
        totals={**totals, "by_service_type": by_type},
        groups=_cap(groups, notes, "groups") if step.group_by == "patient" else groups,
        facts=[_enc_fact(conn, e, log) for e in shown],
        calculation=calc,
        exclusions=[{"encounter": _short(e["encounter_key"]), "date": e["service_date"],
                     "service_type": e["service_type"], "reason": e["exclusion_reason"],
                     "records": _docs_of(conn, e["claim_ids"], log)} for e in excluded] if sc.include_excluded else [],
        conflicts=_conflicts(conn, shown_keys, log),
        decisions=_decisions(conn, shown_keys, log, rules=("R0", "R1", "R2", "R3", "R4", "R7", "R9")),
        notes=notes,
    )
    if sc.include_evidence:
        env["evidence"] = _evidence(conn, [c for e in shown for c in e["claim_ids"]], log)
    env["sql"] = log.statements
    return env


def compliance(conn, step: ComplianceStep) -> dict:
    log, sc = SqlLog(), step.scope
    patients = patients_in_scope(conn, sc, log)
    weeks_all, runs, facts, calc = [], [], [], []
    for p in patients:
        weeks = weekly_compliance(conn, p["mrn"], sc.start, sc.end, log, Scope)
        for w in weeks:
            ev_lines = []
            for ev in w["evaluations"]:
                t = ev["totals"]
                ev_lines.append(f"{ev['plan_days']}: days {_fmt_bound(t['therapy_days'])}, minutes "
                                f"{_fmt_bound(t['minutes'])} -> " + "; ".join(f"{r['metric']} {r['status']}" for r in ev["requirements"]))
            calc.append(f"{p['mrn']} week {w['week_start']}: " + (" | ".join(ev_lines) or "no plan in effect")
                        + f" => {w['status']}")
            weeks_all.append(w)
        if step.consecutive_below:
            runs.append({"patient": p["mrn"], **consecutive_runs(weeks, step.consecutive_below)})
    notes: list[str] = []
    # minute expressions per week for traceability (rows come from the projection; no re-query)
    for w in weeks_all:
        for ev in w["evaluations"]:
            ev["minutes_calculation"] = _minutes_expr(ev.pop("_rows"))
    weeks_shown = _cap(weeks_all, notes, "weeks")
    enc_keys = sorted({k for w in weeks_shown for ev in w["evaluations"] for k in ev["encounters"]})
    for w in weeks_shown:
        for ev in w["evaluations"]:
            ev["encounters"] = [_short(k) for k in ev["encounters"]]
    # encounters in the period that do NOT count toward any goal, with reasons (drafts, charges, no-shows, ...)
    not_counted = _cap([e for e in select_encounters(conn, sc, log, include_excluded=True) if e["eligible"] == "no"],
                       notes, "exclusions")
    exclusions = [{"encounter": _short(e["encounter_key"]), "date": e["service_date"], "week_start": e["week_start"],
                   "service_type": e["service_type"], "reason": e["exclusion_reason"],
                   "records": _docs_of(conn, e["claim_ids"], log)} for e in not_counted]
    evidence_decisions = _decisions(conn, [e["encounter_key"] for e in not_counted] + enc_keys, log, rules=("R2", "R3"))
    summary = defaultdict(int)
    for w in weeks_all:
        summary[w["status"]] += 1
    totals = {"weeks_by_status": dict(summary), "patients": len(patients)}
    if step.consecutive_below:
        rs = defaultdict(int)
        for r in runs:
            rs[r["status"]] += 1
        totals["patients_by_run_status"] = dict(rs)
        if len(runs) > DETAIL_LIMIT:              # collection scale: list the patients that qualify
            runs = [r for r in runs if r["status"] != "no"]
    shown_patients = sorted({w["mrn"] for w in weeks_shown})
    plan_ids = sorted({c for m in shown_patients for r in plan_requirements(conn, m, log) for c in r["claim_ids"]})
    env = _envelope(step, log, totals=totals, groups=weeks_shown, facts=_cap(runs, notes, "runs"),
                    calculation=calc[:DETAIL_LIMIT], exclusions=exclusions,
                    conflicts=_conflicts(conn, enc_keys, log),
                    decisions=_decisions(conn, enc_keys, log, rules=("R4", "R9")) + evidence_decisions, notes=notes)
    if sc.include_evidence:
        env["evidence"] = _evidence(conn, plan_ids, log)
    env["sql"] = log.statements
    return env


def timeline(conn, step: TimelineStep) -> dict:
    log, sc = SqlLog(), step.scope
    facts, claim_ids = [], []
    encs = select_encounters(conn, sc, log, include_excluded=True) if {"encounters", "documents", "decisions"} & set(step.kinds) else []
    keys = [e["encounter_key"] for e in encs]
    if "encounters" in step.kinds:
        for e in encs:
            facts.append({"kind": "encounter", "date": e["service_date"], **_enc_fact(conn, e, log)})
            claim_ids += e["claim_ids"]
    if "documents" in step.kinds and encs:
        ids = sorted({c for e in encs for c in e["claim_ids"]})
        rows = log.run(conn, f"SELECT c.claim_id, c.doc_label, c.evidence_type, c.subject_key, c.payload, c.sha256 "
                             f"FROM claims c WHERE c.claim_id IN ({','.join('?' * len(ids))}) ORDER BY c.doc_label", ids)
        enc_of = {c: e["encounter_key"] for e in encs for c in e["claim_ids"]}
        per_doc: dict[str, dict] = {}
        for r in rows:
            meta = log.run(conn, "SELECT payload FROM claims WHERE sha256=? AND kind='document'", (r["sha256"],))
            dm = json.loads(meta[0]["payload"]) if meta else {}
            p = json.loads(r["payload"])
            d = per_doc.setdefault(r["doc_label"], {"kind": "document", "doc_id": r["doc_label"], "title": dm.get("title"),
                                                     "signed_at": dm.get("signed_at"), "received_at": dm.get("received_at"),
                                                     "finality": dm.get("finality"), "assertions": []})
            d["assertions"].append({"encounter": _short(enc_of[r["claim_id"]]), "record_type": r["evidence_type"],
                                    "disposition": p.get("disposition"), "arrival": p.get("patient_arrival"),
                                    "departure": p.get("patient_departure"),
                                    "contact_intervals": [f"{i['start']}–{i['end']}" for i in p.get("patient_contact_intervals") or []],
                                    "nontherapeutic": [f"{i['kind']} {i['start']}–{i['end']}" for i in p.get("nontherapeutic_intervals") or []],
                                    "stated_minutes": p.get("stated_minutes")})
            claim_ids.append(r["claim_id"])
        rel = log.run(conn, "SELECT doc_label, payload FROM claims WHERE kind='relation' AND subject_key IN "
                            f"({','.join('?' * len(encs))})", [e["encounter_id"] or "" for e in encs])
        for r in rel:
            p = json.loads(r["payload"])
            if r["doc_label"] in per_doc and p["type"] in ("corrects_field", "retransmits_original", "companion_record"):
                per_doc[r["doc_label"]].setdefault("relations", []).append(
                    {k: v for k, v in p.items() if v is not None and k != "quote"})
        facts += sorted(per_doc.values(), key=lambda d: (d.get("signed_at") or d.get("received_at") or "", d["doc_id"]))
    assess = []
    if "assessments" in step.kinds:
        q = ("SELECT * FROM assessments WHERE completed_date BETWEEN ? AND ?"
             + ("" if sc.patients == "all" else f" AND mrn IN ({','.join('?' * len(sc.patients))})")
             + " ORDER BY mrn, completed_date")
        for r in log.run(conn, q, [str(sc.start), str(sc.end)] + ([] if sc.patients == "all" else list(sc.patients))):
            prim, copies = json.loads(r["claim_ids"]), json.loads(r["copy_claim_ids"])
            assess.append(r["assessment_key"])
            facts.append({"kind": "assessment", "date": r["completed_date"], "patient": r["mrn"],
                          "instrument": r["instrument"], "total_score": r["total_score"],
                          "item_scores": json.loads(r["item_scores"]), "form_id": r["form_id"], "status": r["status"],
                          "recorded_in": _docs_of(conn, prim, log),
                          "copies_not_counted": _docs_of(conn, copies, log)})
            claim_ids += prim + copies
    if "observations" in step.kinds:
        q = ("SELECT * FROM observations WHERE obs_date BETWEEN ? AND ?"
             + ("" if sc.patients == "all" else f" AND mrn IN ({','.join('?' * len(sc.patients))})"))
        params = [str(sc.start), str(sc.end)] + ([] if sc.patients == "all" else list(sc.patients))
        if step.observation_domains:
            q += f" AND domain IN ({','.join('?' * len(step.observation_domains))})"
            params += list(step.observation_domains)
        q += " ORDER BY mrn, obs_date, domain, observation_key"
        for r in log.run(conn, q, params):
            ids = json.loads(r["claim_ids"])
            facts.append({"kind": "observation", "date": r["obs_date"], "patient": r["mrn"], "domain": r["domain"],
                          "source": r["source"], "statement": r["statement"], "documents": _docs_of(conn, ids, log)})
            claim_ids += ids
    facts.sort(key=lambda f: (f.get("date") or f.get("signed_at") or "", f["kind"] != "encounter"))
    decisions = _decisions(conn, keys + assess, log) if ("decisions" in step.kinds or "encounters" in step.kinds
                                                         or "assessments" in step.kinds) else []
    env = _envelope(step, log, facts=facts, decisions=decisions, conflicts=_conflicts(conn, keys + assess, log))
    if encs:
        env["totals"] = aggregate([e for e in encs if e["eligible"] != "no"])
        env["calculation"] = [f"patient-present minutes = {_minutes_expr(encs)} = {_fmt_bound(env['totals']['minutes'])}"]
    if sc.include_evidence:
        env["evidence"] = _evidence(conn, claim_ids, log)
    env["sql"] = log.statements
    return env


def compare(conn, step: CompareStep) -> dict:
    log, sc = SqlLog(), step.scope
    notes, sides_all, used = [], [], []
    patients = patients_in_scope(conn, sc, log)
    for p in patients:
        if step.split == "plan_change":
            reqs = plan_requirements(conn, p["mrn"], log)
            starts = plan_change_dates(reqs, sc.start, sc.end)
            if not starts:
                notes.append(f"{p['mrn']}: no treatment-plan change takes effect inside {sc.start}..{sc.end}; "
                             f"plans on file: {sorted({(r['doc_label'], r['effective_start'], r['effective_end']) for r in reqs})}")
                continue
            split = str(starts[0])
            notes.append(f"{p['mrn']}: split at plan change effective {split}"
                         + (f"; further changes on {[str(s) for s in starts[1:]]} not split" if len(starts) > 1 else ""))
        else:
            split = str(step.split)
        from datetime import date as _d
        sp = _d.fromisoformat(split)
        sides = []
        for name, a, b in (("before", sc.start, sp - timedelta(days=1)), ("after", sp, sc.end)):
            if b < a:
                continue
            sub = Scope(patients=[p["mrn"]], start=a, end=b, service_types=sc.service_types, include_excluded=False,
                        include_evidence=False)
            encs = select_encounters(conn, sub, log)
            t = aggregate(encs)
            weeks = ((b - a).days + 1) / 7
            by_type = {ty: {k: v for k, v in aggregate([e for e in encs if e["service_type"] == ty]).items()
                            if k in ("sessions", "minutes")} for ty in sorted({e["service_type"] for e in encs})}
            sides.append({"patient": p["mrn"], "side": name, "period": f"{a}..{b}", "weeks": round(weeks, 2), **t,
                          "minutes_per_week": bound(t["minutes"]["low"] / weeks, (t["minutes"]["high"] / weeks) if t["minutes"]["high"] is not None else None),
                          "by_service_type": by_type, "encounters": [_short(e["encounter_key"]) for e in encs],
                          "minutes_calculation": _minutes_expr(encs)})
            used += encs
        sides_all += sides
    keys = [e["encounter_key"] for e in used]
    excluded = [e for e in select_encounters(conn, sc, log, include_excluded=True) if e["eligible"] == "no"]
    env = _envelope(step, log, groups=sides_all, notes=notes,
                    facts=[_enc_fact(conn, e, log) for e in used],
                    exclusions=[{"encounter": _short(e["encounter_key"]), "date": e["service_date"],
                                 "service_type": e["service_type"], "reason": e["exclusion_reason"]} for e in excluded],
                    conflicts=_conflicts(conn, keys, log),
                    decisions=_decisions(conn, keys, log, rules=("R2", "R3", "R4")))
    if sc.include_evidence:
        env["evidence"] = _evidence(conn, [c for e in used for c in e["claim_ids"]], log)
    env["sql"] = log.statements
    return env


def bound(lo, hi):
    return {"low": round(lo, 1), "high": None if hi is None else round(hi, 1)}
