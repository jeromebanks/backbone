"""The four domain operators. Thin by design: they select from the reconciled abstraction and call project.py;
no clinical rule is implemented here. Every operator returns the same machine-readable envelope:

  {op, params, totals, groups, facts, calculation, exclusions, conflicts, decisions, evidence, notes, sql}
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

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

def _var_limit(conn) -> int:
    """Host parameters one statement may bind on this connection (999 on old SQLite builds, 32766 since 3.32)."""
    return conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)


def _batches(conn, items: list, *, reserved: int = 0, width: int = 1) -> list[list]:
    """Split an IN-list so that no statement exceeds the connection's SQLite variable limit (`reserved` other
    parameters share the statement, `width` placeholders per item). A list that fits is one batch, unchanged, so the
    logged SQL is exactly what a single statement would be. A longer list is de-duplicated and sorted, so batches
    cover contiguous key ranges and a per-batch `ORDER BY <key>, ...` concatenates into the global order."""
    room = max(1, (_var_limit(conn) - reserved) // width)
    if len(items) <= room:
        return [list(items)]
    items = sorted(set(items))
    return [items[i:i + room] for i in range(0, len(items), room)]


def _marks(n: int) -> str:
    return ",".join("?" * n)


def _shared_labels(conn, labels, log: SqlLog) -> set[str]:
    """The subset of `labels` that more than one document in the corpus carries (doc_label is not an identity).
    One scan per operator call, on first need, cached on the call's SqlLog (there is no index on doc_label, so a
    per-label lookup would scan the table every time)."""
    labels = set(labels)
    if not labels:
        return set()
    if "_shared_labels" not in log.__dict__:
        log.__dict__["_shared_labels"] = {r["doc_label"] for r in log.run(
            conn, "SELECT doc_label FROM documents GROUP BY doc_label HAVING COUNT(*) > 1")}
    return labels & log.__dict__["_shared_labels"]


def _doc_ref(label: str, sha: str, shared: set[str]) -> str:
    """How a document is named in lists: its label, plus a short sha when the label is not unique (#40)."""
    return f"{label} [{sha[:12]}]" if label in shared else label


def _evidence(conn, claim_ids: list[str], log: SqlLog) -> list[dict]:
    if not claim_ids:
        return []
    rows = []
    for b in _batches(conn, sorted(set(claim_ids))):
        rows += log.run(conn, f"SELECT c.claim_id, c.doc_label, c.kind, c.evidence_type, c.evidence, d.paths, c.sha256 "
                              f"FROM claims c JOIN documents d ON d.sha256 = c.sha256 "
                              f"WHERE c.claim_id IN ({_marks(len(b))}) ORDER BY c.doc_label, c.claim_id", b)
    rows.sort(key=lambda r: (r["doc_label"], r["claim_id"]))
    shared = _shared_labels(conn, {r["doc_label"] for r in rows}, log)
    out = []
    for r in rows:
        spans = [s for s in json.loads(r["evidence"]) if s["line_start"]]
        if not spans:
            continue
        out.append({"claim_id": r["claim_id"], "doc_id": r["doc_label"],
                    **({"doc_sha": r["sha256"][:12]} if r["doc_label"] in shared else {}),
                    "file": json.loads(r["paths"])[0].split("/")[-1], "record_type": r["evidence_type"] or r["kind"],
                    "passages": [{"lines": f"{s['line_start']}-{s['line_end']}" if s["line_end"] != s["line_start"]
                                  else str(s["line_start"]), "quote": s["quote"]} for s in spans]})
    return out


def _decisions(conn, mrn_keys: list[str], log: SqlLog, rules: tuple | None = None) -> list[dict]:
    if not mrn_keys:
        return []
    out = []
    for b in _batches(conn, mrn_keys, reserved=len(rules or ())):
        sql = f"SELECT subject_key, rule, outcome, reason FROM decisions WHERE subject_key IN ({_marks(len(b))})"
        params = list(b)
        if rules:
            sql += f" AND rule IN ({_marks(len(rules))})"
            params += list(rules)
        sql += " ORDER BY subject_key, decision_id"
        out += [{"subject": _short(r["subject_key"]), "rule": r["rule"], "outcome": r["outcome"], "reason": r["reason"]}
                for r in log.run(conn, sql, params)]
    return out


def _conflicts(conn, keys: list[str], log: SqlLog) -> list[dict]:
    if not keys:
        return []
    out = []
    for b in _batches(conn, keys):
        for r in log.run(conn, f"SELECT subject_key, field, candidates, resolution FROM conflicts WHERE subject_key IN "
                               f"({_marks(len(b))}) ORDER BY subject_key, conflict_id", b):
            cands = json.loads(r["candidates"])
            for c in cands:
                if c.get("claim_ids"):
                    c["documents"] = _docs_of(conn, c["claim_ids"], log)
            out.append({"subject": _short(r["subject_key"]), "field": r["field"], "resolution": r["resolution"],
                        "candidates": cands})
    return out


def _docs_of(conn, claim_ids: list[str], log: SqlLog) -> list[str]:
    """The documents the claims come from, one entry per document (sha256), named by `_doc_ref`."""
    if not claim_ids:
        return []
    pairs = set()
    for b in _batches(conn, claim_ids):
        pairs |= {(r["doc_label"], r["sha256"]) for r in log.run(
            conn, f"SELECT DISTINCT doc_label, sha256 FROM claims WHERE claim_id IN ({_marks(len(b))})", b)}
    shared = _shared_labels(conn, {lab for lab, _ in pairs}, log)
    return sorted(_doc_ref(lab, sha, shared) for lab, sha in pairs)


def _claim_date(kind: str, p: dict) -> tuple[str | None, str | None]:
    """The [first, last] day a claim is about, from the claim's own payload (None = open/unknown)."""
    if kind == "plan_requirement":
        return p.get("effective_start"), p.get("effective_end")
    d = {"service_event": p.get("service_date"), "assessment": p.get("completed_date"),
         "observation": p.get("date"), "relation": p.get("original_date")}.get(kind)
    return d, d


def _rejections(conn, sc: Scope, log: SqlLog, kinds: tuple | None = None) -> list[dict]:
    """Claims that rule R0 rejected (a quote could not be located in the source) for the patients in scope (#39).
    The rejection is dated by the claim's own date; undated claims are always listed, since they cannot be placed.
    `kinds` restricts the claim kinds; a claim that states a service type must match `scope.service_types`."""
    rows = []
    sql = ("SELECT d.mrn, d.reason, c.claim_id, c.kind, c.doc_label, c.sha256, c.payload FROM decisions d "
           "JOIN claims c ON c.claim_id = json_extract(d.claim_ids, '$[0]') WHERE d.rule = 'R0'")
    if sc.patients == "all":
        rows = log.run(conn, sql + " ORDER BY d.mrn, c.claim_id")
    else:
        for b in _batches(conn, list(sc.patients)):
            rows += log.run(conn, sql + f" AND d.mrn IN ({_marks(len(b))}) ORDER BY d.mrn, c.claim_id", b)
    lo, hi = str(sc.start), str(sc.end)
    shared = _shared_labels(conn, {r["doc_label"] for r in rows}, log) if rows else set()
    out = []
    for r in rows:
        p = json.loads(r["payload"])
        first, last = _claim_date(r["kind"], p)
        if (first and first > hi) or (last and last < lo) or (kinds and r["kind"] not in kinds):
            continue
        if sc.service_types and p.get("service_type") and p["service_type"] not in sc.service_types:
            continue
        # shaped like an encounter exclusion (encounter/date/service_type/reason/records) so readers treat it alike
        out.append({"encounter": p.get("encounter_id"), "date": first, "service_type": p.get("service_type"),
                    "reason": r["reason"], "records": [_doc_ref(r["doc_label"], r["sha256"], shared)],
                    "rule": "R0", "patient": r["mrn"], "record_kind": r["kind"], "claim_id": r["claim_id"]})
    return sorted(out, key=lambda x: (x["patient"], x["date"] or "", x["claim_id"]))


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
    facts = [_enc_fact(conn, e, log) for e in shown]
    exclusions = [{"encounter": _short(e["encounter_key"]), "date": e["service_date"],
                   "service_type": e["service_type"], "reason": e["exclusion_reason"],
                   "records": _docs_of(conn, e["claim_ids"], log)} for e in excluded] if sc.include_excluded else []
    if sc.include_excluded:                   # evidence rejected before reconciliation (R0) also does not count
        exclusions += _cap(_rejections(conn, sc, log, kinds=("service_event", "relation")), notes, "rejected claims")
    env = _envelope(
        step, log,
        totals={**totals, "by_service_type": by_type},
        groups=_cap(groups, notes, "groups") if step.group_by == "patient" else groups,
        facts=facts,
        calculation=calc,
        exclusions=exclusions,
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
    if sc.service_types:
        # A plan's goals define which service types they count; judging them on a narrower selection would give a
        # confident verdict the plan does not define. Refuse explicitly instead of ignoring the filter (#21).
        reason = ("compliance does not accept scope.service_types: each treatment-plan requirement counts the service "
                  "types the plan states. Drop service_types, or use care with service_types for delivered totals.")
        return _envelope(step, log, totals={"unsupported": reason}, notes=[reason])
    patients = patients_in_scope(conn, sc, log)
    weeks_all, runs, facts, calc = [], [], [], []
    for p in patients:
        weeks = weekly_compliance(conn, p["mrn"], sc.start, sc.end, log, Scope)
        for w in weeks:
            ev_lines = []
            for ev in w["evaluations"]:
                t = ev["totals"]
                ev_lines.append(f"{ev['plan_days']}: days {_fmt_bound(t['therapy_days'])}, minutes "
                                f"{_fmt_bound(t['minutes'])} -> " + "; ".join(
                                    f"{r['metric']} {r['status']}" + (f" ({_fmt_bound(r['value'])} over {r['counted_service_types']})"
                                                                      if "counted_service_types" in r else "")
                                    for r in ev["requirements"]))
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
    facts, claim_ids, notes = [], [], []
    encs = select_encounters(conn, sc, log, include_excluded=True) if {"encounters", "documents", "decisions"} & set(step.kinds) else []
    shown = _cap(encs, notes, "encounters")          # per-row detail is capped; totals below cover every encounter
    keys = [e["encounter_key"] for e in shown]
    if "encounters" in step.kinds:
        for e in shown:
            facts.append({"kind": "encounter", "date": e["service_date"], **_enc_fact(conn, e, log)})
            claim_ids += e["claim_ids"]
    if "documents" in step.kinds and shown:
        rows = []
        for b in _batches(conn, sorted({c for e in shown for c in e["claim_ids"]})):
            rows += log.run(conn, f"SELECT c.claim_id, c.doc_label, c.evidence_type, c.subject_key, c.payload, c.sha256 "
                                  f"FROM claims c WHERE c.claim_id IN ({_marks(len(b))}) ORDER BY c.doc_label", b)
        rows.sort(key=lambda r: (r["doc_label"], r["claim_id"]))
        enc_of = {c: e["encounter_key"] for e in shown for c in e["claim_ids"]}
        per_doc: dict[str, dict] = {}           # keyed by sha256: doc_label is not unique (across or within patients)
        doc_claims: dict[str, list] = defaultdict(list)
        for r in rows:
            meta = log.run(conn, "SELECT payload FROM claims WHERE sha256=? AND kind='document'", (r["sha256"],))
            dm = json.loads(meta[0]["payload"]) if meta else {}
            p = json.loads(r["payload"])
            d = per_doc.setdefault(r["sha256"], {"kind": "document", "doc_id": r["doc_label"], "title": dm.get("title"),
                                                     "signed_at": dm.get("signed_at"), "received_at": dm.get("received_at"),
                                                     "finality": dm.get("finality"), "assertions": []})
            if "service_date" not in p:         # a correction relation (#23): it is listed under relations below
                claim_ids.append(r["claim_id"])
                continue
            d["assertions"].append({"encounter": _short(enc_of[r["claim_id"]]), "record_type": r["evidence_type"],
                                    "disposition": p.get("disposition"), "arrival": p.get("patient_arrival"),
                                    "departure": p.get("patient_departure"),
                                    "contact_intervals": [f"{i['start']}–{i['end']}" for i in p.get("patient_contact_intervals") or []],
                                    "nontherapeutic": [f"{i['kind']} {i['start']}–{i['end']}" for i in p.get("nontherapeutic_intervals") or []],
                                    "stated_minutes": p.get("stated_minutes")})
            doc_claims[r["sha256"]].append(r["claim_id"])
        shared = _shared_labels(conn, {d["doc_id"] for d in per_doc.values()}, log)
        for sha, d in per_doc.items():
            if d["doc_id"] in shared:           # same-label documents stay distinguishable (#40)
                d["doc_sha"] = sha[:12]
        # Relations a shown document states about an in-scope encounter. Encounter IDs are unique only within a
        # patient, so match on (patient, encounter ID); attach to the stating document by sha256, never by label.
        pairs = sorted({(e["mrn"], e["encounter_id"]) for e in shown if e["encounter_id"]})
        shas = sorted(per_doc)
        rel = []
        if pairs and shas and len(shas) + 2 * len(pairs) <= _var_limit(conn):
            rel = log.run(conn, "SELECT sha256, payload FROM claims WHERE kind='relation' AND verified=1 "
                                f"AND sha256 IN ({_marks(len(shas))}) "
                                f"AND (patient_mrn, subject_key) IN (VALUES {','.join(['(?,?)'] * len(pairs))}) "
                                "ORDER BY subject_key, claim_id",
                          shas + [x for pr in pairs for x in pr])
        elif pairs and shas:                    # too many for one statement: select per document, match pairs here
            wanted = set(pairs)
            for b in _batches(conn, shas):
                rel += [r for r in log.run(conn, "SELECT sha256, payload, patient_mrn, subject_key FROM claims "
                                                 f"WHERE kind='relation' AND verified=1 AND sha256 IN ({_marks(len(b))}) "
                                                 "ORDER BY subject_key, claim_id", b)
                        if (r["patient_mrn"], r["subject_key"]) in wanted]
        for r in rel:
            p = json.loads(r["payload"])
            if p["type"] in ("corrects_field", "retransmits_original", "companion_record"):
                per_doc[r["sha256"]].setdefault("relations", []).append(
                    {k: v for k, v in p.items() if v is not None and k != "quote"})
        docs = _cap(sorted(per_doc.items(), key=lambda kv: (
            kv[1].get("signed_at") or kv[1].get("received_at") or "", kv[1]["doc_id"], kv[0])), notes, "documents")
        facts += [d for _, d in docs]
        claim_ids += [c for sha, _ in docs for c in doc_claims[sha]]
    assess = []
    if "assessments" in step.kinds:
        found = []
        for b in ([None] if sc.patients == "all" else _batches(conn, list(sc.patients), reserved=2)):
            q = ("SELECT * FROM assessments WHERE completed_date BETWEEN ? AND ?"
                 + ("" if b is None else f" AND mrn IN ({_marks(len(b))})") + " ORDER BY mrn, completed_date")
            found += log.run(conn, q, [str(sc.start), str(sc.end)] + ([] if b is None else b))
        for r in _cap(found, notes, "assessments"):
            prim, copies = json.loads(r["claim_ids"]), json.loads(r["copy_claim_ids"])
            assess.append(r["assessment_key"])
            facts.append({"kind": "assessment", "date": r["completed_date"], "patient": r["mrn"],
                          "instrument": r["instrument"], "total_score": r["total_score"],
                          "item_scores": json.loads(r["item_scores"]), "form_id": r["form_id"], "status": r["status"],
                          "recorded_in": _docs_of(conn, prim, log),
                          "copies_not_counted": _docs_of(conn, copies, log)})
            claim_ids += prim + copies
    if "observations" in step.kinds:
        doms = list(step.observation_domains or [])
        found = []
        for b in ([None] if sc.patients == "all" else _batches(conn, list(sc.patients), reserved=2 + len(doms))):
            q = ("SELECT * FROM observations WHERE obs_date BETWEEN ? AND ?"
                 + ("" if b is None else f" AND mrn IN ({_marks(len(b))})"))
            params = [str(sc.start), str(sc.end)] + ([] if b is None else b)
            if doms:
                q += f" AND domain IN ({_marks(len(doms))})"
                params += doms
            q += " ORDER BY mrn, obs_date, domain, observation_key"
            found += log.run(conn, q, params)
        for r in _cap(found, notes, "observations"):
            ids = json.loads(r["claim_ids"])
            facts.append({"kind": "observation", "date": r["obs_date"], "patient": r["mrn"], "domain": r["domain"],
                          "source": r["source"], "statement": r["statement"], "documents": _docs_of(conn, ids, log)})
            claim_ids += ids
    facts.sort(key=lambda f: (f.get("date") or f.get("signed_at") or "", f["kind"] != "encounter"))
    decisions = _decisions(conn, keys + assess, log) if ("decisions" in step.kinds or "encounters" in step.kinds
                                                         or "assessments" in step.kinds) else []
    conflicts = _conflicts(conn, keys + assess, log)
    rejected = _cap(_rejections(conn, sc, log), notes, "rejected claims")     # R0: evidence that never counted
    env = _envelope(step, log, facts=facts, decisions=decisions, conflicts=conflicts, exclusions=rejected,
                    notes=notes)
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
        sp = date.fromisoformat(split)
        if not sc.start < sp <= sc.end:          # both sides are clipped to the scope, which is never widened (#20)
            notes.append(f"{p['mrn']}: split {sp} is not inside the scope {sc.start}..{sc.end} (it must fall after the "
                         f"first day and on or before the last), so there is nothing to compare: only the "
                         f"'{'after' if sp <= sc.start else 'before'}' side is reported, clipped to the scope")
        sides = []
        for name, a, b in (("before", sc.start, min(sp - timedelta(days=1), sc.end)), ("after", max(sp, sc.start), sc.end)):
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
    shown = _cap(used, notes, "facts")
    keys = [e["encounter_key"] for e in shown]
    excluded = _cap([e for e in select_encounters(conn, sc, log, include_excluded=True) if e["eligible"] == "no"],
                    notes, "exclusions")
    env = _envelope(step, log, groups=sides_all, notes=notes,       # groups are compare's totals: never capped
                    facts=[_enc_fact(conn, e, log) for e in shown],
                    exclusions=[{"encounter": _short(e["encounter_key"]), "date": e["service_date"],
                                 "service_type": e["service_type"], "reason": e["exclusion_reason"]} for e in excluded],
                    conflicts=_conflicts(conn, keys, log),
                    decisions=_decisions(conn, keys, log, rules=("R2", "R3", "R4")))
    if sc.include_evidence:
        env["evidence"] = _evidence(conn, [c for e in shown for c in e["claim_ids"]], log)
    env["sql"] = log.statements
    return env


def bound(lo, hi):
    return {"low": round(lo, 1), "high": None if hi is None else round(hi, 1)}
