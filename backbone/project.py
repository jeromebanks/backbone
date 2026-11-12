"""Projection layer: the ONLY place that turns reconciled encounters into counts, bounds and plan verdicts.

Operators call these functions; none of them re-implements eligibility, minutes or plan semantics.

Bounds semantics (every quantity is [low, high]):
  eligible='yes'       contributes [1, 1] session and [minutes_low, minutes_high] minutes
  eligible='uncertain' contributes [0, 1] session and [0, minutes_high] minutes (high None = unbounded)
  eligible='no'        contributes nothing
Plan verdicts: MET if the requirement holds at both bounds, NOT_MET if it holds at neither, else UNDETERMINED.
"""
from __future__ import annotations

import json
import operator
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

INF = float("inf")


@dataclass
class SqlLog:
    statements: list[dict] = field(default_factory=list)

    def run(self, conn: sqlite3.Connection, sql: str, params: list | tuple = ()):
        self.statements.append({"sql": " ".join(sql.split()), "params": list(params)})
        return conn.execute(sql, params).fetchall()


def d(s: str) -> date:
    return date.fromisoformat(s)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


# --------------------------------------------------------------------------------------------- selection

def patients_in_scope(conn, scope, log: SqlLog) -> list[dict]:
    if scope.patients == "all":
        rows = log.run(conn, "SELECT mrn, name, dob FROM patients ORDER BY mrn")
    else:
        q = ",".join("?" * len(scope.patients))
        rows = log.run(conn, f"SELECT mrn, name, dob FROM patients WHERE mrn IN ({q}) ORDER BY mrn", scope.patients)
    return [dict(r) for r in rows]


def select_encounters(conn, scope, log: SqlLog, *, include_excluded: bool | None = None,
                      service_types: list[str] | None = None) -> list[dict]:
    include_excluded = scope.include_excluded if include_excluded is None else include_excluded
    sql = ("SELECT encounter_key, mrn, encounter_id, service_date, week_start, service_type, modality, disposition, "
           "attended, patient_present, is_therapy, eligible, exclusion_reason, minutes_low, minutes_high, "
           "minutes_status, calculation, claim_ids, flags FROM v_encounter_week WHERE service_date BETWEEN ? AND ?")
    params: list = [str(scope.start), str(scope.end)]
    if scope.patients != "all":
        sql += f" AND mrn IN ({','.join('?' * len(scope.patients))})"
        params += list(scope.patients)
    types = service_types if service_types is not None else scope.service_types
    if types:
        sql += f" AND service_type IN ({','.join('?' * len(types))})"
        params += list(types)
    if not include_excluded:
        sql += " AND eligible != 'no'"
    sql += " ORDER BY mrn, service_date, encounter_key"
    out = []
    for r in log.run(conn, sql, params):
        e = dict(r)
        e["claim_ids"], e["flags"] = json.loads(e["claim_ids"]), json.loads(e["flags"])
        out.append(e)
    return out


# --------------------------------------------------------------------------------------------- bounds

def contribution(e: dict) -> dict:
    if e["eligible"] == "yes":
        lo, hi = e["minutes_low"], e["minutes_high"]
        return {"sessions": (1, 1), "minutes": (lo if lo is not None else 0, hi if hi is not None else INF)}
    if e["eligible"] == "uncertain":
        hi = e["minutes_high"]
        return {"sessions": (0, 1), "minutes": (0, hi if hi is not None else INF)}
    return {"sessions": (0, 0), "minutes": (0, 0)}


def aggregate(encs: list[dict]) -> dict:
    """Totals with bounds over a set of encounters."""
    s_lo = s_hi = m_lo = m_hi = 0.0
    days_lo, days_hi = set(), set()
    uncertain = []
    for e in encs:
        c = contribution(e)
        s_lo += c["sessions"][0]; s_hi += c["sessions"][1]
        m_lo += c["minutes"][0]; m_hi += c["minutes"][1]
        day = (e["mrn"], e["service_date"])          # a therapy day belongs to a patient
        if e["eligible"] == "yes":
            days_lo.add(day); days_hi.add(day)
        elif e["eligible"] == "uncertain":
            days_hi.add(day)
        if e["eligible"] == "uncertain" or (e["eligible"] == "yes" and e["minutes_low"] != e["minutes_high"]):
            uncertain.append(e["encounter_key"])
    return {
        "sessions": bound(s_lo, s_hi),
        "therapy_days": bound(len(days_lo), len(days_hi)),
        "minutes": bound(m_lo, m_hi),
        "hours": bound(round(m_lo / 60, 2), round(m_hi / 60, 2) if m_hi != INF else INF),
        "uncertain_encounters": uncertain,
    }


def bound(lo, hi) -> dict:
    lo = int(lo) if float(lo).is_integer() else lo
    hi = None if hi == INF else (int(hi) if float(hi).is_integer() else hi)
    return {"low": lo, "high": hi, "status": "established" if lo == hi else "bounded"}


def group_key(e: dict, group_by: str) -> str:
    return {"none": "all", "service_type": e["service_type"], "day": e["service_date"],
            "week": e["week_start"], "patient": e["mrn"]}[group_by]


# --------------------------------------------------------------------------------------------- plans

def plan_requirements(conn, mrn: str, log: SqlLog) -> list[dict]:
    rows = log.run(conn, "SELECT * FROM plan_requirements WHERE mrn=? ORDER BY effective_start, metric", (mrn,))
    out = []
    for r in rows:
        p = dict(r)
        p["counted_types"], p["claim_ids"] = json.loads(p["counted_types"]), json.loads(p["claim_ids"])
        out.append(p)
    return out


def plan_in_effect(reqs: list[dict], day: date) -> list[dict]:
    return [r for r in reqs
            if (r["effective_start"] is None or d(r["effective_start"]) <= day)
            and (r["effective_end"] is None or day <= d(r["effective_end"]))]


def _req_sig(r: dict) -> tuple:
    return (r["metric"], r["comparator"], r["threshold"], tuple(sorted(r["counted_types"])))


def requirement_sets_on(reqs: list[dict], day: date) -> tuple[list[list[dict]], list[str]]:
    """The requirement set(s) in effect on `day` (R9).

    - Identical requirements restated by several documents count once.
    - For each metric, the requirement whose effective period started most recently is in effect (a revision
      supersedes an earlier plan from its effective date; precedence is by effective date, never document date).
    - If several DIFFERENT requirements for one metric share that latest start date, the record conflicts: every
      alternative is returned, so callers evaluate each and report UNDETERMINED when they disagree.
    """
    active = plan_in_effect(reqs, day)
    notes: list[str] = []
    by_metric: dict[str, list[dict]] = {}
    for r in active:
        by_metric.setdefault(r["metric"], []).append(r)
    choices: list[list[dict]] = []
    for metric, rs in sorted(by_metric.items()):
        latest = max((r["effective_start"] or "") for r in rs)
        current = [r for r in rs if (r["effective_start"] or "") == latest]
        superseded = sorted({r["doc_label"] for r in rs if (r["effective_start"] or "") != latest})
        if superseded:
            notes.append(f"{metric}: requirement effective {latest} ({sorted({r['doc_label'] for r in current})}) "
                         f"supersedes {superseded}")
        distinct: dict[tuple, dict] = {}
        for r in sorted(current, key=lambda r: r["requirement_key"]):
            distinct.setdefault(_req_sig(r), r)
        if len(distinct) > 1:
            notes.append(f"{metric}: conflicting requirements in effect on {day} from "
                         f"{sorted({r['doc_label'] for r in current})}; each alternative evaluated")
        choices.append(list(distinct.values()))
    sets: list[list[dict]] = [[]]
    for alts in choices:
        sets = [s + [a] for s in sets for a in alts]
    return ([s for s in sets if s] or []), notes


_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq}
_METRIC = {"therapy_days": "therapy_days", "patient_present_minutes": "minutes", "sessions": "sessions"}


def evaluate_requirement(req: dict, totals: dict) -> dict:
    metric = _METRIC.get(req["metric"])
    if metric is None:
        return {"requirement": req["requirement_key"], "status": "UNDETERMINED", "reason": f"unsupported metric {req['metric']}"}
    b = totals[metric]
    lo, hi = b["low"], INF if b["high"] is None else b["high"]
    op = _OPS[req["comparator"]]
    at_lo, at_hi = op(lo, req["threshold"]), op(hi, req["threshold"])
    status = "MET" if (at_lo and at_hi) else "NOT_MET" if not (at_lo or at_hi) else "UNDETERMINED"
    shown = lo if lo == hi else f"{lo}–{'∞' if hi == INF else hi}"
    return {"requirement": req["requirement_key"], "metric": req["metric"], "goal": f"{req['comparator']} {req['threshold']:g}",
            "value": b, "status": status,
            "reason": f"{req['metric']} {shown} vs goal {req['comparator']} {req['threshold']:g}"}


def weekly_compliance(conn, mrn: str, start: date, end: date, log: SqlLog, scope_cls) -> list[dict]:
    """Per Mon–Sun week overlapping [start, end]: requirements in effect, totals with bounds, three-valued verdict.

    Weekly goals are judged on the WHOLE in-scope week (days covered by some plan). If different requirement sets
    are in effect during the week (a revision mid-week, or conflicting plans), the whole-week totals are evaluated
    against each set; agreement gives that verdict, disagreement gives UNDETERMINED (R9). A partial segment is never
    compared against a full-week goal.
    """
    reqs = plan_requirements(conn, mrn, log)
    weeks = []
    ws = week_start(start)
    while ws <= end:
        we = ws + timedelta(days=6)
        lo, hi = max(ws, start), min(we, end)
        days = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        notes: list[str] = []
        if (hi - lo).days + 1 < 7:
            notes.append(f"partial week: {lo}..{hi} is inside the requested period ({(hi - lo).days + 1} of 7 days)")
        sets: dict[tuple, tuple[list[dict], list[date]]] = {}
        covered: list[date] = []
        for day in days:
            day_sets, day_notes = requirement_sets_on(reqs, day)
            notes += [n for n in day_notes if n not in notes]
            if not day_sets:
                continue
            covered.append(day)
            for s in day_sets:
                sets.setdefault(tuple(sorted(_req_sig(r) for r in s)), (s, []))[1].append(day)
        evaluations = []
        if covered:
            ev_lo, ev_hi = min(covered), max(covered)
            covered_set = {str(x) for x in covered}
            if len(covered) < len(days):
                notes.append(f"a treatment plan is in effect on {len(covered)} of {len(days)} days of this week "
                             f"({ev_lo}..{ev_hi}); only those days are evaluated")
            for s, sdays in sets.values():
                counted = sorted({t for r in s for t in r["counted_types"]})
                sub = scope_cls(patients=[mrn], start=ev_lo, end=ev_hi, service_types=counted,
                                include_excluded=False, include_evidence=False)
                encs = [e for e in select_encounters(conn, sub, log, include_excluded=False)
                        if e["service_date"] in covered_set]
                totals = aggregate(encs)
                evals = [evaluate_requirement(r, totals) for r in s]
                st = ("NOT_MET" if any(e["status"] == "NOT_MET" for e in evals)
                      else "MET" if all(e["status"] == "MET" for e in evals) else "UNDETERMINED")
                ev = {"plan_days": f"{ev_lo}..{ev_hi}", "plan_documents": sorted({r['doc_label'] for r in s}),
                      "counted_service_types": counted, "totals": totals, "requirements": evals,
                      "status": st, "encounters": [e["encounter_key"] for e in encs], "_rows": encs}
                if len(sets) > 1:
                    ev["requirement_set_in_effect"] = f"{min(sdays)}..{max(sdays)}"
                evaluations.append(ev)
        verdicts = {ev["status"] for ev in evaluations}
        if not verdicts:
            status = "NO_PLAN"
        elif len(verdicts) == 1:
            status = next(iter(verdicts))
        else:
            status = "UNDETERMINED"
        if len(evaluations) > 1:
            notes.append("more than one requirement set applies within this week; whole-week totals evaluated "
                         "against each: " + ", ".join(f"{e['requirement_set_in_effect']} {e['plan_documents']} -> "
                                                     f"{e['status']}" for e in evaluations)
                         + ("; they disagree, so the week is UNDETERMINED (R9)" if len(verdicts) > 1 else "; they agree"))
        weeks.append({"mrn": mrn, "week_start": str(ws), "week_end": str(we), "evaluated_days": f"{lo}..{hi}",
                      "status": status, "evaluations": evaluations, "notes": notes})
        ws += timedelta(days=7)
    return weeks


def plan_change_dates(reqs: list[dict], start: date, end: date) -> list[date]:
    """Days in (start, end] on which the requirement set in effect differs from the previous day's."""
    def sig(day):
        sets, _ = requirement_sets_on(reqs, day)
        return sorted(tuple(sorted(_req_sig(r) for r in s)) for s in sets)
    out, prev = [], sig(start)
    for i in range(1, (end - start).days + 1):
        day = start + timedelta(days=i)
        cur = sig(day)
        if cur != prev and cur:          # a (different) requirement set takes effect
            out.append(day)
        prev = cur
    return out


def consecutive_runs(weeks: list[dict], n: int) -> dict:
    """Runs of >= n consecutive weeks below requirements. 'definite' uses NOT_MET only; 'possible' also counts
    UNDETERMINED weeks, so a patient whose inclusion depends on unresolved documentation is identifiable."""
    def runs(ok):
        out, cur = [], []
        for w in weeks:
            if ok(w["status"]):
                cur.append(w["week_start"])
            else:
                if len(cur) >= n:
                    out.append(cur)
                cur = []
        if len(cur) >= n:
            out.append(cur)
        return out
    definite = runs(lambda s: s == "NOT_MET")
    possible = runs(lambda s: s in ("NOT_MET", "UNDETERMINED"))
    status = "yes" if definite else "depends_on_unresolved" if possible else "no"
    return {"status": status, "definite_runs": definite, "possible_runs": possible if not definite else []}
