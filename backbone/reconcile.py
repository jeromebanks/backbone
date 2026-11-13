"""Deterministic reconciliation: verified claims -> clinical layer (encounters, intervals, plans, assessments).

Pure function `reconcile_patient(mrn, claims)` + a persistence wrapper. Every consequential choice is written
to `decisions` (rule id, outcome, reason, claim ids) and every unresolved disagreement to `conflicts`, so a
reviewer can see why a session counted or not and which records contributed.

Rules (RULESET_VERSION in __init__):
  R0  claims whose quotes cannot be located in the source text are excluded.
  R1  encounter identity: group by encounter ID; otherwise match on same date + service type (and overlapping
      times if both known); otherwise keep as a separate unidentified contact.
  R2  draft/template text, billing rows and unsigned drafts are not attendance evidence.
  R3  explicit field corrections replace the corrected value only for that field; retransmitted/copied records
      are linked to their original and carry no independent weight. Precedence never follows document date.
  R4  evidence tiers: clinical notes, attendance registers/corrections, platform logs (tier 1) outrank schedule
      listings and notices (tier 2). Disagreement within the deciding tier -> disputed (kept as bounds).
  R5  a therapy session counts if the service is psychotherapy (individual/group/family), it was attended, and
      the patient was present. Unknown attendance is 'uncertain' (bounds), never silently 0 or 1.
  R6  minutes = |patient-present intervals - non-therapeutic intervals| (breaks, disconnections, patient-absent
      portions). Stated minute totals are cross-checks only.
  R7  one patient cannot be present in two encounters at once; overlaps are flagged.
  R8  assessments are identified by (instrument, completion date, form id); copies/imports are not new assessments.
  R9  treatment-plan requirements apply by effective date (evaluated in project.py); same-day pre-signature care noted.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from . import RULESET_VERSION
from .intervals import fmt_set, normalize, overlaps, subtract, to_min, total

THERAPY_TYPES = {"individual_therapy", "group_therapy", "family_therapy"}
TIER1 = {"clinical_note", "attendance_record", "attendance_correction", "platform_log"}
TIER2 = {"schedule_listing", "administrative_notice", "other"}
NOT_EVIDENCE = {"draft_template": "draft/template text is not attendance evidence",
                "billing": "a billing/charge row is not attendance evidence",
                "retransmitted_copy": "a retransmitted/copied record is not independent evidence"}
ATTENDED = {"attended_full": "yes", "attended_partial": "yes", "attended": "yes",
            "no_show": "no", "patient_cancelled": "no", "clinic_cancelled": "no",
            "scheduled_only": "unknown", "unknown": "unknown"}
FIELD_MAP = {"arrival": "patient_arrival", "departure": "patient_departure", "disposition": "disposition"}


@dataclass
class Claim:
    claim_id: str
    sha256: str
    doc_label: str
    kind: str
    subject_key: str | None
    evidence_type: str | None
    payload: dict
    evidence: list
    verified: bool
    doc: dict = field(default_factory=dict)       # the document-level claim payload (signed, finality, ...)
    eff: dict = field(default_factory=dict)       # effective (corrected) field values
    tier: int | None = None
    excluded_reason: str | None = None


@dataclass
class Result:
    mrn: str
    encounters: list[dict] = field(default_factory=list)
    intervals: list[dict] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    assessments: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def decide(self, subject, rule, outcome, reason, claim_ids):
        self.decisions.append({"subject_key": subject, "rule": rule, "outcome": outcome, "reason": reason,
                               "claim_ids": sorted(set(claim_ids))})


def _norm_id(x: str | None) -> str | None:
    return x.strip().upper() if x and x.strip() else None


def _cite(c: Claim) -> str:
    return c.doc_label


# --------------------------------------------------------------------------------------------- encounters

def _classify(c: Claim) -> None:
    et = c.evidence_type or "other"
    if c.doc.get("finality") == "draft" and et not in ("billing",):
        et = "draft_template"
    if et in NOT_EVIDENCE:
        c.tier, c.excluded_reason = None, NOT_EVIDENCE[et]
    elif et in TIER1:
        c.tier = 1
    else:
        c.tier = 2


def _group_events(events: list[Claim], res: Result) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    meta: dict[str, tuple[str, str, list]] = {}   # key -> (date, type, intervals)
    mrn = res.mrn

    def ivs(c: Claim):
        p = c.payload
        out = [(to_min(i["start"]), to_min(i["end"])) for i in p.get("patient_contact_intervals") or []]
        if p.get("scheduled"):
            out.append((to_min(p["scheduled"]["start"]), to_min(p["scheduled"]["end"])))
        return normalize(out)

    ided = [c for c in events if _norm_id(c.payload.get("encounter_id"))]
    unided = [c for c in events if not _norm_id(c.payload.get("encounter_id"))]
    for c in ided:
        key = f"{mrn}|{_norm_id(c.payload['encounter_id'])}"
        groups[key].append(c)
        if key not in meta:
            meta[key] = (c.payload["service_date"], c.payload["service_type"], ivs(c))
    for c in sorted(unided, key=lambda c: c.claim_id):
        d, t, iv = c.payload["service_date"], c.payload["service_type"], ivs(c)
        cands = [k for k, (md, mt, miv) in meta.items()
                 if md == d and mt == t and (not iv or not miv or overlaps(iv, miv))]
        if len(cands) == 1:
            groups[cands[0]].append(c)
            res.decide(cands[0], "R1", "matched_without_id",
                       f"{c.doc_label} names no encounter ID; matched on date {d} + service type {t}", [c.claim_id])
            continue
        n = sum(1 for k in meta if k.startswith(f"{mrn}|U-{d}-{t}")) + 1
        key = f"{mrn}|U-{d}-{t}-{n}"
        groups[key].append(c)
        meta[key] = (d, t, iv)
        why = "ambiguous: several candidates" if cands else "no matching encounter"
        res.decide(key, "R1", "unidentified_contact", f"{c.doc_label}: {why} ({d}, {t}); kept as a separate contact",
                   [c.claim_id])
    return groups


def _apply_corrections(group: list[Claim], corrections: list[Claim], key: str, res: Result) -> None:
    for c in group:
        c.eff = {k: c.payload.get(k) for k in ("patient_arrival", "patient_departure", "disposition")}
    for corr in corrections:
        f = FIELD_MAP.get(corr.payload.get("field") or "")
        if not f:
            continue
        old, new = corr.payload.get("old_value"), corr.payload.get("new_value")
        for c in group:
            if c.sha256 == corr.sha256 or c.eff.get(f) is None:
                continue
            if old is not None and str(c.eff[f]).strip() == str(old).strip():
                c.eff[f] = new
                res.decide(key, "R3", "field_corrected",
                           f"{c.doc_label} {corr.payload['field']} {old} replaced by {new} per explicit correction in "
                           f"{corr.doc_label} (correction applies to this field only)", [c.claim_id, corr.claim_id])


def _vote(values: list[str]) -> tuple[str, bool]:
    vals = set(values)
    if "yes" in vals and "no" in vals:
        return "disputed", True
    if "yes" in vals:
        return "yes", False
    if "no" in vals:
        return "no", False
    return "unknown", False


def _reconcile_encounter(key: str, group: list[Claim], corrections: list[Claim], retransmitted: set[str],
                         res: Result) -> tuple[dict, list[dict]]:
    flags: list[str] = []
    for c in group:
        _classify(c)
        if c.tier is not None and c.sha256 in retransmitted:
            c.tier, c.excluded_reason = None, NOT_EVIDENCE["retransmitted_copy"]
        if c.excluded_reason:
            is_copy = c.excluded_reason == NOT_EVIDENCE["retransmitted_copy"]
            res.decide(key, "R3" if is_copy else "R2",
                       "evidence_excluded", f"{c.doc_label} ({c.evidence_type}): {c.excluded_reason}"
                       + (f"; it states disposition '{c.payload['disposition']}'" if c.payload.get("disposition") not in (None, "unknown") else ""),
                       [c.claim_id])
    _apply_corrections(group, corrections, key, res)
    t1 = [c for c in group if c.tier == 1]
    t2 = [c for c in group if c.tier == 2]
    usable = t1 + t2
    ids = [c.claim_id for c in group]

    # service type (R4): tier 1 majority, then tier 2, then anything
    pool = t1 or t2 or group
    types = Counter(c.payload["service_type"] for c in pool)
    stype = sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if len(types) > 1:
        flags.append(f"service type disagreement: {dict(types)}")
        res.conflicts.append({"subject_key": key, "field": "service_type", "resolution": f"majority:{stype}",
                              "candidates": [{"value": t, "claim_ids": [c.claim_id for c in pool if c.payload['service_type'] == t]} for t in types]})
    dates = Counter(c.payload["service_date"] for c in pool)
    sdate = sorted(dates.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if len(dates) > 1:
        flags.append(f"service date disagreement: {dict(dates)}")
    modality = next((c.payload["modality"] for c in t1 if c.payload.get("modality") not in (None, "unknown")),
                    next((c.payload["modality"] for c in usable if c.payload.get("modality") not in (None, "unknown")), "unknown"))
    eid = _norm_id(next((c.payload.get("encounter_id") for c in group if c.payload.get("encounter_id")), None))

    # attendance (R4/R5)
    attended, deciding = "unknown", []
    for tier in (t1, t2):
        vals = [ATTENDED.get(c.eff.get("disposition") or "unknown", "unknown") for c in tier]
        a, disputed = _vote(vals)
        if a != "unknown":
            attended, deciding = a, tier
            if disputed:
                res.conflicts.append({"subject_key": key, "field": "attendance", "resolution": "disputed",
                                      "candidates": [{"value": v, "claim_ids": [c.claim_id for c in tier if ATTENDED.get(c.eff.get('disposition') or 'unknown') == v]} for v in ("yes", "no")]})
            break
    dispositions = Counter(c.eff.get("disposition") for c in deciding
                           if ATTENDED.get(c.eff.get("disposition") or "unknown") == attended)
    disposition = "unknown"
    if dispositions:
        specific = sorted(d for d in dispositions if d not in ("attended", "unknown", "scheduled_only"))
        if len(specific) == 1:
            disposition = specific[0]
        elif len(specific) > 1:
            disposition = "attended" if attended == "yes" else specific[0]
            flags.append(f"disposition detail differs: {specific}")
        else:
            disposition = sorted(dispositions.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if deciding:
        res.decide(key, "R4", f"attended={attended}",
                   f"decided by tier-{deciding[0].tier} records: " +
                   ", ".join(f"{c.doc_label} ({c.evidence_type}: {c.eff.get('disposition')})" for c in deciding),
                   [c.claim_id for c in deciding])

    # patient presence
    pres_vals = []
    for c in (t1 or t2):
        p = c.payload.get("patient_present")
        pres_vals.append({"yes": "yes", "partial": "yes", "no": "no"}.get(p, "unknown"))
    present, pres_disputed = _vote(pres_vals)
    if attended == "no":
        present = "no"
    if any(c.payload.get("patient_present") == "partial" for c in (t1 or t2)) and present == "yes":
        present = "partial"

    # eligibility (R5)
    is_therapy = stype in THERAPY_TYPES
    reason = None
    if not is_therapy:
        eligible, reason = "no", f"not a psychotherapy service ({stype})"
    elif attended == "no":
        eligible, reason = "no", f"not attended ({disposition})"
    elif present == "no":
        eligible, reason = "no", "patient not present"
    elif attended in ("yes",) and present in ("yes", "partial"):
        eligible = "yes"
    else:
        eligible, reason = "uncertain", f"attendance {attended}, presence {present}"
    res.decide(key, "R5", f"eligible={eligible}", reason or f"{stype}, attended, patient present", ids)

    # minutes (R6)
    rows: list[dict] = []
    excl: list[tuple[int, int, str, str]] = []
    for c in usable:
        for n in c.payload.get("nontherapeutic_intervals") or []:
            s, e = to_min(n["start"]), to_min(n["end"])
            if s is not None and e is not None and e > s:
                excl.append((s, e, n["kind"], c.claim_id))
    excl_ivs = normalize([(s, e) for s, e, _, _ in excl])
    for s, e, kind, cid in sorted(set(excl)):
        rows.append({"encounter_key": key, "kind": "excluded", "start_min": s, "end_min": e, "label": kind,
                     "claim_ids": [cid]})
    sched = next(((to_min(c.payload["scheduled"]["start"]), to_min(c.payload["scheduled"]["end"]))
                  for c in usable if c.payload.get("scheduled")), None)
    if sched and None not in sched:
        rows.append({"encounter_key": key, "kind": "scheduled", "start_min": sched[0], "end_min": sched[1],
                     "label": "scheduled", "claim_ids": [c.claim_id for c in usable if c.payload.get("scheduled")]})

    cands: dict[tuple, list[Claim]] = defaultdict(list)
    basis: dict[tuple, str] = {}
    for c in t1:
        ci = normalize([(to_min(i["start"]), to_min(i["end"])) for i in c.payload.get("patient_contact_intervals") or []])
        if ci:
            cands[tuple(ci)].append(c); basis.setdefault(tuple(ci), "stated contact intervals")
            continue
        a, d = to_min(c.eff.get("patient_arrival")), to_min(c.eff.get("patient_departure"))
        if a is not None and d is not None and d > a:
            cands[((a, d),)].append(c); basis.setdefault(((a, d),), "arrival–departure")
    if not cands and sched and None not in sched and any(c.eff.get("disposition") == "attended_full" for c in t1):
        cands[(sched,)] = [c for c in t1 if c.eff.get("disposition") == "attended_full"]
        basis[(sched,)] = "attended full scheduled session"

    m_low = m_high = None
    calc = None
    if eligible == "no" and not is_therapy:
        status = "not_applicable"
    elif eligible == "no":
        status, m_low, m_high = "not_applicable", 0, 0
    elif cands:
        mins = {}
        for iv, cs in cands.items():
            eff = subtract(list(iv), excl_ivs)
            mins[iv] = total(eff)
            rows.append({"encounter_key": key, "kind": "present", "start_min": iv[0][0], "end_min": iv[-1][1],
                         "label": f"{basis[iv]}: {fmt_set(list(iv))} per {', '.join(sorted({x.doc_label for x in cs}))}",
                         "claim_ids": [x.claim_id for x in cs]})
        m_low, m_high = min(mins.values()), max(mins.values())
        parts = []
        for iv, cs in sorted(cands.items(), key=lambda kv: mins[kv[0]]):
            ex = [f"{k} {fmt_set([(s, e)])}" for s, e, k, _ in sorted(set((s, e, k, '') for s, e, k, _ in excl))]
            parts.append(f"{fmt_set(list(iv))} ({basis[iv]}; {', '.join(sorted({x.doc_label for x in cs}))})"
                         + (f" − {' − '.join(ex)}" if ex and total(list(iv)) != mins[iv] else "") + f" = {mins[iv]} min")
        calc = " | ".join(parts)
        if len(cands) > 1:
            status = "disputed"
            res.conflicts.append({"subject_key": key, "field": "patient_present_interval", "resolution": "disputed",
                                  "candidates": [{"value": fmt_set(list(iv)), "minutes": mins[iv],
                                                  "claim_ids": [x.claim_id for x in cs]} for iv, cs in cands.items()]})
            res.decide(key, "R4", "minutes_disputed",
                       "tier-1 records give different patient-contact intervals and none corrects the other: " + calc
                       + f"; carried as bounds [{m_low}, {m_high}]", [x.claim_id for cs in cands.values() for x in cs])
        else:
            status = "established"
        # stated-minute cross-check (R6)
        for c in t1:
            sm = c.payload.get("stated_minutes")
            if sm is not None and not (m_low <= sm <= m_high):
                flags.append(f"{c.doc_label} states {sm} min; patient-present computation gives "
                             f"{m_low if m_low == m_high else f'{m_low}–{m_high}'} min")
    else:
        status = "unknown"
        m_low = 0
        m_high = total(subtract([sched], excl_ivs)) if sched and None not in sched else None
        calc = ("no patient arrival/departure or contact interval documented; bounds 0.."
                + (f"{m_high} (scheduled {fmt_set([sched])} minus exclusions)" if m_high is not None else "unbounded"))
        res.decide(key, "R6", "minutes_unknown", calc, ids)
    if calc and status == "established":
        res.decide(key, "R6", f"minutes={m_low}", calc, [x.claim_id for cs in cands.values() for x in cs]
                   + [cid for *_, cid in excl])

    enc = {
        "encounter_key": key, "mrn": res.mrn, "encounter_id": eid, "service_date": sdate, "service_type": stype,
        "modality": modality, "disposition": disposition, "attended": attended, "patient_present": present,
        "is_therapy": int(is_therapy), "eligible": eligible, "exclusion_reason": reason,
        "minutes_low": m_low, "minutes_high": m_high, "minutes_status": status, "calculation": calc,
        "claim_ids": sorted(ids), "flags": flags, "ruleset_version": RULESET_VERSION,
        "_present_sets": [list(iv) for iv in cands] if eligible != "no" else [],
        "_superseded": [],
    }
    # remember pre-correction presence for the overlap rationale
    for c in t1:
        a, d = to_min(c.payload.get("patient_arrival")), to_min(c.payload.get("patient_departure"))
        ea, ed = to_min(c.eff.get("patient_arrival")), to_min(c.eff.get("patient_departure"))
        if (a, d) != (ea, ed) and a is not None and d is not None:
            enc["_superseded"].append(((a, d), c.doc_label))
    return enc, rows


def _overlap_checks(encs: list[dict], res: Result) -> None:
    by_date = defaultdict(list)
    for e in encs:
        by_date[e["service_date"]].append(e)
    for d, es in by_date.items():
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                for sa in a["_present_sets"]:
                    for sb in b["_present_sets"]:
                        if overlaps(sa, sb):
                            msg = f"patient-present intervals overlap: {a['encounter_key']} {fmt_set(sa)} vs {b['encounter_key']} {fmt_set(sb)}"
                            a["flags"].append(msg); b["flags"].append(msg)
                            res.decide(a["encounter_key"], "R7", "overlap", msg, [])
                for x, y in ((a, b), (b, a)):
                    for iv, label in x["_superseded"]:
                        for sy in y["_present_sets"]:
                            if overlaps([iv], sy):
                                res.decide(x["encounter_key"], "R7", "correction_consistent",
                                           f"the superseded value in {label} ({fmt_set([iv])}) would overlap "
                                           f"{y['encounter_key']} {fmt_set(sy)}; the corrected value does not", [])


# --------------------------------------------------------------------------------------------- other subjects

def _counted_types(p: dict) -> list[str]:
    """Service types a requirement counts: the stated list (all psychotherapy if none is stated) minus the stated
    exclusions. Folding the exclusions in here keeps them from being discarded (#7)."""
    return sorted(set(p["counted_service_types"] or THERAPY_TYPES) - set(p.get("excluded_service_types") or ()))


def _plans(plan_claims: list[Claim], res: Result) -> None:
    """Plan requirements, one row per (source document, requirement).

    - Requirements from a draft document are not operative (R2, mirroring `_classify`); the claims stay as evidence.
    - Rows are grouped per document (sha256, never the non-unique label) and full requirement identity, so a plan
      with several goals for one metric keeps them all. Restatements across documents are separate rows, and
      `project.requirement_sets_on` counts identical ones once.
    - The key keeps the readable `mrn|plan|label|metric|start` form; only when that collides (two goals for one
      metric and start, or two documents sharing a label) is a hash of the document and full identity appended.
    """
    groups: dict[tuple, list[Claim]] = defaultdict(list)
    for c in plan_claims:
        p = c.payload
        if c.doc.get("finality") == "draft":
            res.decide(f"{res.mrn}|plan|{c.doc_label}", "R2", "plan_not_operative",
                       f"{c.doc_label} is a draft; its {p['metric']} {p['comparator']} {p['threshold']:g} requirement "
                       "is kept as evidence but does not take effect", [c.claim_id])
            continue
        k = (c.sha256, p["metric"], p["comparator"], p["threshold"], p["period"], p.get("effective_start"),
             p.get("effective_end"), tuple(_counted_types(p)), bool(p["requires_patient_present"]))
        groups[k].append(c)
    rows = []
    for k, cs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        c0 = sorted(cs, key=lambda c: c.claim_id)[0]
        p = c0.payload
        base = f"{res.mrn}|plan|{c0.doc_label}|{p['metric']}|{p.get('effective_start')}"
        counted = _counted_types(p)
        rows.append((base, hashlib.sha1(repr(k).encode()).hexdigest()[:10], {
            "mrn": res.mrn, "doc_label": c0.doc_label, "metric": p["metric"],
            "comparator": p["comparator"], "threshold": p["threshold"], "period": p["period"],
            "counted_types": counted,
            "requires_patient_present": int(p["requires_patient_present"]),
            "effective_start": p.get("effective_start"), "effective_end": p.get("effective_end"),
            "signed_at": c0.doc.get("signed_at"), "claim_ids": sorted(c.claim_id for c in cs)}, cs))
    collisions = Counter(base for base, *_ in rows)
    restated: dict[tuple, list[tuple[str, dict, list[Claim]]]] = defaultdict(list)
    for base, h, row, cs in sorted(rows, key=lambda r: (r[0], r[1])):
        rk = base if collisions[base] == 1 else f"{base}|{h}"
        res.plans.append({"requirement_key": rk, **row})
        p = cs[0].payload
        restated[tuple(str(x) for x in (row["metric"], row["comparator"], row["threshold"], row["period"],
                                        row["effective_start"], row["effective_end"], row["counted_types"],
                                        row["requires_patient_present"]))].append((rk, row, cs))
        excluded = sorted(set(p["counted_service_types"]) & set(p.get("excluded_service_types") or ()))
        if excluded:
            res.decide(rk, "R9", "excluded_types_removed", f"{row['doc_label']} both counts and excludes {excluded}; "
                       f"the exclusion applies, counted types are {row['counted_types']}", [c.claim_id for c in cs])
        if not row["counted_types"]:
            res.decide(rk, "R9", "no_counted_types", f"{row['doc_label']}: every counted service type is excluded; "
                       "the requirement cannot be evaluated", [c.claim_id for c in cs])
        if len(cs) > 1:
            res.decide(rk, "R3", "duplicate_plan_text", f"{len(cs)} records state the same requirement",
                       [c.claim_id for c in cs])
    for same in restated.values():
        if len({cs[0].sha256 for _, _, cs in same}) > 1:
            res.decide(same[0][0], "R3", "plan_restated",
                       f"{len(same)} documents ({', '.join(row['doc_label'] for _, row, _ in same)}) state the same "
                       f"{same[0][1]['metric']} requirement; it counts once", [c.claim_id for _, _, cs in same for c in cs])


def _assessments(acl: list[Claim], copy_docs: set[str], res: Result) -> None:
    groups: dict[tuple, list[Claim]] = defaultdict(list)
    for c in acl:
        p = c.payload
        groups[(p["instrument"].upper().replace(" ", ""), p.get("completed_date"))].append(c)
    for (inst, d), cs in sorted(groups.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        forms = sorted({c.payload.get("form_id") for c in cs if c.payload.get("form_id")})
        buckets = {f: [c for c in cs if c.payload.get("form_id") in (f, None)] for f in forms} if len(forms) > 1 else {forms[0] if forms else None: cs}
        for form, bcs in buckets.items():
            copies = [c for c in bcs if c.payload.get("is_copy_of_earlier") or c.sha256 in copy_docs]
            prim = [c for c in bcs if c not in copies] or copies
            scores = {c.payload.get("total_score") for c in bcs}
            key = f"{res.mrn}|{inst}|{d}|{form or '-'}"
            status = "disputed" if len(scores) > 1 else "distinct"
            items = sorted({i for c in bcs for i in c.payload.get("item_scores") or []})
            res.assessments.append({
                "assessment_key": key, "mrn": res.mrn, "instrument": prim[0].payload["instrument"],
                "total_score": prim[0].payload.get("total_score"), "item_scores": items, "completed_date": d,
                "form_id": form, "status": status, "claim_ids": sorted(c.claim_id for c in prim),
                "copy_claim_ids": sorted(c.claim_id for c in copies if c not in prim)})
            if copies and prim is not copies:
                res.decide(key, "R8", "copy_not_distinct",
                           f"{', '.join(sorted({c.doc_label for c in copies}))} restate(s) the {inst} completed {d}"
                           + (f" (form {form})" if form else "") + f" recorded in {', '.join(sorted({c.doc_label for c in prim}))}; "
                           "not counted as a separate assessment", [c.claim_id for c in bcs])
            if status == "disputed":
                res.conflicts.append({"subject_key": key, "field": "total_score", "resolution": "disputed",
                                      "candidates": [{"value": s, "claim_ids": [c.claim_id for c in bcs if c.payload.get('total_score') == s]} for s in scores]})


def _observations(ocl: list[Claim], res: Result) -> None:
    groups: dict[tuple, list[Claim]] = defaultdict(list)
    for c in ocl:
        q = " ".join((c.payload.get("quote") or "").lower().split())
        groups[(c.payload["date"], c.payload["domain"], c.doc_label, q)].append(c)
    for (d, dom, label, q), cs in sorted(groups.items()):
        c0 = cs[0]
        key = f"{res.mrn}|obs|" + hashlib.sha1(f"{d}{dom}{label}{q}".encode()).hexdigest()[:12]
        res.observations.append({"observation_key": key, "mrn": res.mrn, "obs_date": d, "domain": dom,
                                 "source": c0.payload["source"], "statement": c0.payload["statement"],
                                 "claim_ids": sorted(c.claim_id for c in cs)})


# --------------------------------------------------------------------------------------------- entry points

def reconcile_patient(mrn: str, claims: list[Claim]) -> Result:
    res = Result(mrn)
    docs = {c.sha256: c.payload for c in claims if c.kind == "document"}
    for c in claims:
        c.doc = docs.get(c.sha256, {})
    for c in claims:
        if not c.verified and c.kind != "document":
            # Keyed like the subject it would have supported: the patient's encounter when the claim names one
            # (so operators attach it to that encounter), else a per-claim key under the patient.
            eid = _norm_id(c.payload.get("encounter_id")) if c.kind in ("service_event", "relation") else None
            res.decide(f"{mrn}|{eid}" if eid else f"{mrn}|claim|{c.claim_id}", "R0", "claim_rejected",
                       f"{c.doc_label} {c.kind}: quote not found in source text", [c.claim_id])
    claims = [c for c in claims if c.verified or c.kind == "document"]
    rel = [c for c in claims if c.kind == "relation"]
    corrections = defaultdict(list)
    retransmitted: set[str] = set()
    copy_docs: set[str] = set()
    for r in rel:
        t, eid = r.payload["type"], _norm_id(r.payload.get("encounter_id"))
        if t == "corrects_field" and eid:
            corrections[f"{mrn}|{eid}"].append(r)
        elif t == "retransmits_original":
            retransmitted.add(r.sha256)
        elif t == "copies_measurement":
            copy_docs.add(r.sha256)

    events = [c for c in claims if c.kind == "service_event" and c.payload.get("service_date")]
    groups = _group_events(events, res)
    encs = []
    for key in sorted(groups):
        enc, rows = _reconcile_encounter(key, groups[key], corrections.get(key, []), retransmitted, res)
        encs.append(enc)
        res.intervals.extend(rows)
    _overlap_checks(encs, res)
    res.encounters = encs
    _plans([c for c in claims if c.kind == "plan_requirement"], res)
    # R9 note: care on a plan's first effective day that precedes its signature (once per encounter and signature,
    # even when several documents restate the plan)
    noted: set[tuple] = set()
    for p in res.plans:
        if not (p["signed_at"] and p["effective_start"]) or p["metric"] != "therapy_days":
            continue
        signed_min = to_min(p["signed_at"][11:16]) if len(p["signed_at"]) >= 16 else None
        for e in encs:
            if e["eligible"] != "no" and e["service_date"] == p["effective_start"] and e["_present_sets"] and signed_min:
                if e["_present_sets"][0][0][0] < signed_min and (e["encounter_key"], p["signed_at"]) not in noted:
                    noted.add((e["encounter_key"], p["signed_at"]))
                    res.decide(e["encounter_key"], "R9", "counted_under_plan",
                               f"session began before the plan signature ({p['signed_at']}) on the plan's first "
                               f"effective day; counted because plan effectivity is by date", p["claim_ids"])
    _assessments([c for c in claims if c.kind == "assessment"], copy_docs, res)
    _observations([c for c in claims if c.kind == "observation"], res)
    return res


def load_claims(conn: sqlite3.Connection, mrn: str) -> list[Claim]:
    rows = conn.execute("SELECT * FROM claims WHERE patient_mrn=? ORDER BY claim_id", (mrn,)).fetchall()
    return [Claim(r["claim_id"], r["sha256"], r["doc_label"], r["kind"], r["subject_key"], r["evidence_type"],
                  json.loads(r["payload"]), json.loads(r["evidence"]), bool(r["verified"])) for r in rows]


def persist(conn: sqlite3.Connection, res: Result) -> None:
    mrn = res.mrn
    for t in ("encounter_intervals",):
        conn.execute(f"DELETE FROM {t} WHERE encounter_key IN (SELECT encounter_key FROM encounters WHERE mrn=?)", (mrn,))
    for t in ("encounters", "plan_requirements", "assessments", "observations", "decisions", "conflicts"):
        conn.execute(f"DELETE FROM {t} WHERE mrn=?", (mrn,))
    for e in res.encounters:
        row = {k: v for k, v in e.items() if not k.startswith("_")}
        row["claim_ids"], row["flags"] = json.dumps(row["claim_ids"]), json.dumps(row["flags"])
        conn.execute(f"INSERT INTO encounters({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    for r in res.intervals:
        conn.execute("INSERT INTO encounter_intervals VALUES (?,?,?,?,?,?)",
                     (r["encounter_key"], r["kind"], r["start_min"], r["end_min"], r["label"], json.dumps(r["claim_ids"])))
    for p in res.plans:
        row = dict(p, counted_types=json.dumps(p["counted_types"]), claim_ids=json.dumps(p["claim_ids"]))
        conn.execute(f"INSERT INTO plan_requirements({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    for a in res.assessments:
        row = dict(a, item_scores=json.dumps(a["item_scores"]), claim_ids=json.dumps(a["claim_ids"]),
                   copy_claim_ids=json.dumps(a["copy_claim_ids"]))
        conn.execute(f"INSERT INTO assessments({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    for o in res.observations:
        row = dict(o, claim_ids=json.dumps(o["claim_ids"]))
        conn.execute(f"INSERT INTO observations({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    for d in res.decisions:
        conn.execute("INSERT INTO decisions(mrn, subject_key, rule, outcome, reason, claim_ids, ruleset_version) "
                     "VALUES (?,?,?,?,?,?,?)", (mrn, d["subject_key"], d["rule"], d["outcome"], d["reason"],
                                                json.dumps(d["claim_ids"]), RULESET_VERSION))
    for c in res.conflicts:
        conn.execute("INSERT INTO conflicts(mrn, subject_key, field, candidates, resolution) VALUES (?,?,?,?,?)",
                     (mrn, c["subject_key"], c["field"], json.dumps(c["candidates"], default=str), c["resolution"]))
    conn.execute("UPDATE patients SET reconciled_at=?, ruleset_version=? WHERE mrn=?",
                 (datetime.now().isoformat(timespec="seconds"), RULESET_VERSION, mrn))


def reconcile_patients(conn: sqlite3.Connection, mrns) -> dict:
    out = {}
    for mrn in sorted(set(mrns)):
        claims = load_claims(conn, mrn)
        res = reconcile_patient(mrn, claims)
        with conn:
            persist(conn, res)              # with no claims this clears every derived row of the patient
            orphan = not claims and not conn.execute("SELECT 1 FROM documents WHERE patient_mrn=?", (mrn,)).fetchone()
            if orphan:                      # e.g. its only document was re-attributed or quarantined
                conn.execute("DELETE FROM patients WHERE mrn=?", (mrn,))
        out[mrn] = {"encounters": len(res.encounters), "decisions": len(res.decisions),
                    "conflicts": len(res.conflicts), "assessments": len(res.assessments)}
        if orphan:
            out[mrn]["patient_removed"] = True
    return out
