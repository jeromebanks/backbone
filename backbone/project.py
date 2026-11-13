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

from .reconcile import THERAPY_TYPES

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
    # Rows sharing (mrn, encounter_id) are alternative accounts of ONE encounter whose date or type is disputed
    # (reconcile._add_identity_alternatives; each is 'uncertain'). At most one of them happened, so together they
    # contribute the largest of their bounds, not the sum (#12). Every other row is its own group.
    groups: dict[tuple, list[dict]] = {}
    for e in encs:
        groups.setdefault((e["mrn"], e.get("encounter_id")) if e.get("encounter_id") else (e["encounter_key"],), []).append(e)
    for g in groups.values():
        cs = [contribution(e) for e in g]
        s_lo += max(c["sessions"][0] for c in cs); s_hi += max(c["sessions"][1] for c in cs)
        m_lo += max(c["minutes"][0] for c in cs); m_hi += max(c["minutes"][1] for c in cs)
    for e in encs:
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
    """Full identity of a requirement: two rows with the same signature are restatements of one goal."""
    return (r["metric"], r["comparator"], r["threshold"], tuple(sorted(r["counted_types"])),
            r.get("period", "week_mon_sun"), bool(r.get("requires_patient_present", 1)))


def _source(r: dict) -> str:
    """The document a requirement row came from. Claim ids are `<sha256 prefix>:<kind>:<n>` (ingest.py), so they
    identify the document even when two documents share a label (#38); rows without claims fall back to the label."""
    return r["claim_ids"][0].split(":", 1)[0] if r.get("claim_ids") else r["doc_label"]


def requirement_sets_on(reqs: list[dict], day: date) -> tuple[list[list[dict]], list[str]]:
    """The requirement set(s) in effect on `day` (R9).

    - For each metric, the requirements whose effective period started most recently are in effect (a revision
      supersedes an earlier plan from its effective date; precedence is by effective date, never document date).
    - Requirements for one metric from ONE document apply together (e.g. >= 2 individual and >= 1 group sessions).
    - Identical requirement sets restated by several documents count once.
    - If several documents state DIFFERENT requirement sets for one metric from that latest start date, the record
      conflicts: every alternative is returned, so callers evaluate each and report UNDETERMINED when they disagree.
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
        per_doc: dict[str, dict[tuple, dict]] = {}
        for r in sorted(current, key=lambda r: r["requirement_key"]):
            per_doc.setdefault(_source(r), {}).setdefault(_req_sig(r), r)
        distinct: dict[tuple, list[dict]] = {}          # one alternative per distinct document requirement set
        for reqs_of_doc in per_doc.values():
            distinct.setdefault(tuple(sorted(reqs_of_doc)), list(reqs_of_doc.values()))
        if len(distinct) > 1:
            notes.append(f"{metric}: conflicting requirements in effect on {day} from "
                         f"{sorted({r['doc_label'] for r in current})}; each alternative evaluated")
        choices.append(list(distinct.values()))
    sets: list[list[dict]] = [[]]
    for alts in choices:
        sets = [s + a for s in sets for a in alts]
    return ([s for s in sets if s] or []), notes


_OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq}
_METRIC = {"therapy_days": "therapy_days", "patient_present_minutes": "minutes", "sessions": "sessions"}


def _lower_bound_only(req: dict) -> str | None:
    """Why the projected total is only a LOWER bound for this requirement, if it is. The projection counts eligible
    sessions (R5: psychotherapy, attended, patient present), so it undercounts a goal that also counts other service
    types, or that counts sessions or days without requiring the patient's presence (#7)."""
    other = sorted(set(req.get("counted_types") or ()) - THERAPY_TYPES)
    if other:
        return f"counts {other}, which the projection does not count (only psychotherapy)"
    if not req.get("requires_patient_present", 1) and req["metric"] in ("sessions", "therapy_days"):
        return "does not require patient presence; only patient-present sessions are counted"
    return None


def _verdict(comparator: str, threshold: float, lo, hi) -> str:
    """Three-valued: MET if the goal holds for every value in [lo, hi], NOT_MET if for none, else UNDETERMINED."""
    if comparator == "==":                        # not monotone: an interior value can equal the threshold (#18)
        if lo == hi == threshold:
            return "MET"
        return "NOT_MET" if threshold < lo or threshold > hi else "UNDETERMINED"
    op = _OPS[comparator]                         # monotone: the endpoints decide
    at_lo, at_hi = op(lo, threshold), op(hi, threshold)
    return "MET" if (at_lo and at_hi) else "NOT_MET" if not (at_lo or at_hi) else "UNDETERMINED"


def evaluate_requirement(req: dict, totals: dict) -> dict:
    metric = _METRIC.get(req["metric"])
    if metric is None:
        return {"requirement": req["requirement_key"], "status": "UNDETERMINED", "reason": f"unsupported metric {req['metric']}"}
    b = totals[metric]
    if "counted_types" in req and not req["counted_types"]:
        return {"requirement": req["requirement_key"], "metric": req["metric"],
                "goal": f"{req['comparator']} {req['threshold']:g}", "value": bound(0, 0), "status": "UNDETERMINED",
                "reason": "unsupported: the requirement counts no service type (all of its types are excluded)"}
    partial = _lower_bound_only(req)
    if partial:
        b = {"low": b["low"], "high": None, "status": "bounded"}
    lo, hi = b["low"], INF if b["high"] is None else b["high"]
    status = _verdict(req["comparator"], req["threshold"], lo, hi)
    shown = lo if lo == hi else f"{lo}–{'∞' if hi == INF else hi}"
    return {"requirement": req["requirement_key"], "metric": req["metric"], "goal": f"{req['comparator']} {req['threshold']:g}",
            "value": b, "status": status,
            "reason": f"{req['metric']} {shown} vs goal {req['comparator']} {req['threshold']:g}"
                      + (f" (lower bound only: the requirement {partial})" if partial else "")}


def _evaluate_weekly(req: dict, totals: dict) -> dict:
    """A Mon–Sun week's totals can only judge a Mon–Sun requirement; any other period is UNDETERMINED (#7)."""
    ev = evaluate_requirement(req, totals)
    period = req.get("period", "week_mon_sun")
    if period != "week_mon_sun" and "metric" in ev:
        ev["status"] = "UNDETERMINED"
        ev["reason"] = (f"unsupported: the requirement's period is '{period}', not a Monday–Sunday week, so a weekly "
                        f"total cannot judge it ({ev['reason']})")
    return ev


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
                        if e["service_date"] in covered_set] if counted else []   # [] would mean "no type filter"
                totals = aggregate(encs)
                evals = []
                for r in s:                       # each requirement is counted over its OWN service types (#6)
                    own = sorted(r["counted_types"])
                    if own == counted:
                        evals.append(_evaluate_weekly(r, totals))
                    else:
                        own_totals = aggregate([e for e in encs if e["service_type"] in own])
                        evals.append({**_evaluate_weekly(r, own_totals), "counted_service_types": own})
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
