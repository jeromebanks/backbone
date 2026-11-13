"""Deterministic reconciliation: verified claims -> clinical layer (encounters, intervals, plans, assessments).

Pure function `reconcile_patient(mrn, claims)` + a persistence wrapper. Every consequential choice is written
to `decisions` (rule id, outcome, reason, claim ids) and every unresolved disagreement to `conflicts`, so a
reviewer can see why a session counted or not and which records contributed.

Rules (RULESET_VERSION in __init__):
  R0  claims whose quotes cannot be located in the source text are excluded.
  R1  encounter identity: group by encounter ID; otherwise match on same date + service type (and overlapping
      times if both known, arrival–departure included; corrected service types included); a psychotherapy record
      overlapping in time a psychotherapy contact of another type joins it with the type disputed; otherwise keep
      as a separate unidentified contact. A disputed date/type yields alternative rows of the one encounter (never a
      majority pick).
  R2  draft/template text, billing rows and unsigned drafts are not attendance evidence.
  R3  explicit field corrections replace the corrected value only for that field; retransmitted/copied records
      are linked to their original and carry no independent weight. Precedence never follows document date.
      Correction chains resolve independently of claim order; competing corrections are kept as disputes.
  R4  evidence tiers: clinical notes, attendance registers/corrections, platform logs (tier 1) outrank schedule
      listings and notices (tier 2). Disagreement within the deciding tier -> disputed (kept as bounds).
  R5  a therapy session counts if the service is psychotherapy (individual/group/family), it was attended, and
      the patient was present. Unknown attendance is 'uncertain' (bounds), never silently 0 or 1.
  R6  minutes = |patient-present intervals - non-therapeutic intervals| (breaks, disconnections, patient-absent
      portions), exclusions reconciled per kind (conflicting accounts are alternatives, never unioned); intervals
      the same-day algebra cannot represent (overnight, inverted) give unknown minutes. Stated minute totals are
      cross-checks only.
  R7  one patient cannot be present in two encounters at once; overlaps are flagged.
  R8  assessments are identified by (instrument, completion date, form id); copies/imports are not new assessments.
  R9  treatment-plan requirements apply by effective date (evaluated in project.py); same-day pre-signature care noted.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import get_args

from . import RULESET_VERSION
from .intervals import fmt, fmt_set, normalize, overlaps, subtract, to_min, total
from .schema import ServiceType

THERAPY_TYPES = {"individual_therapy", "group_therapy", "family_therapy"}
TIER1 = {"clinical_note", "attendance_record", "attendance_correction", "platform_log"}
TIER2 = {"schedule_listing", "administrative_notice", "other"}
NOT_EVIDENCE = {"draft_template": "draft/template text is not attendance evidence",
                "billing": "a billing/charge row is not attendance evidence",
                "retransmitted_copy": "a retransmitted/copied record is not independent evidence"}
ATTENDED = {"attended_full": "yes", "attended_partial": "yes", "attended": "yes",
            "no_show": "no", "patient_cancelled": "no", "clinic_cancelled": "no",
            "scheduled_only": "unknown", "unknown": "unknown"}
FIELD_MAP = {"arrival": "patient_arrival", "departure": "patient_departure", "disposition": "disposition",
             "contact_interval": "patient_contact_intervals", "service_type": "service_type"}
SERVICE_TYPES = set(get_args(ServiceType))
_INTERVAL = re.compile(r"\s*(\d{1,2}:\d{2})\s*(?:-|–|—|to)\s*(\d{1,2}:\d{2})\s*")


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
    alts: dict = field(default_factory=dict)      # field -> alternative values when corrections compete (#9)
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


def _group_events(events: list[Claim], res: Result, corrections: dict[str, list[Claim]]) -> dict[str, list[Claim]]:
    groups: dict[str, list[Claim]] = defaultdict(list)
    meta: dict[str, tuple[set, list, list]] = {}  # key -> ({(date, type)}, stated times, actual times)
    corrected: dict[str, set] = defaultdict(set)  # key -> (date, type) pairs reached only through a correction
    mrn = res.mrn

    def ivs(c: Claim):
        """Every time the record states for the contact: contact intervals, schedule, and actual arrival–departure
        when both ends are known (#11: two ID-less sessions known only by arrival/departure must not merge)."""
        p = c.payload
        out = [(to_min(i["start"]), to_min(i["end"])) for i in p.get("patient_contact_intervals") or []]
        if p.get("scheduled"):
            out.append((to_min(p["scheduled"]["start"]), to_min(p["scheduled"]["end"])))
        out.append((to_min(p.get("patient_arrival")), to_min(p.get("patient_departure"))))
        return normalize(out)

    def actual(c: Claim):
        """Times the patient was actually in contact: contact intervals and arrival–departure (not the schedule)."""
        p = c.payload
        out = [(to_min(i["start"]), to_min(i["end"])) for i in p.get("patient_contact_intervals") or []]
        out.append((to_min(p.get("patient_arrival")), to_min(p.get("patient_departure"))))
        return normalize(out)

    def type_edges(key: str) -> list[tuple]:
        out = []
        for r in corrections.get(key, ()):
            if r.payload.get("field") == "service_type":
                old, new = _corr_value("service_type", r.payload.get("old_value")), _corr_value("service_type", r.payload.get("new_value"))
                if old is not None and new is not None and old != new:
                    out.append((old, new, r))
        return out

    ided = [c for c in events if _norm_id(c.payload.get("encounter_id"))]
    unided = [c for c in events if not _norm_id(c.payload.get("encounter_id"))]
    for c in ided:
        key = f"{mrn}|{_norm_id(c.payload['encounter_id'])}"
        groups[key].append(c)
    for key, cs in groups.items():
        # Every (date, type) a record of the encounter states, and every service type a correction of the encounter
        # turns it into (#61: matching before corrections missed an ID-less record of the corrected type; matching on
        # the first record's type alone depended on claim order). The correcting document's own record is never
        # corrected (R3), so its edges do not apply to it here either.
        pairs, iv, act = set(), [], []
        edges = type_edges(key)
        for c in cs:
            d, t = c.payload["service_date"], c.payload["service_type"]
            pairs.add((d, t))
            k0 = _corr_value("service_type", t)
            mine = [e for e in edges if e[2].sha256 != c.sha256]
            if k0 is not None and mine:
                for t2 in _resolve(k0, mine):
                    if (d, t2) not in pairs:
                        corrected[key].add((d, t2))
            iv = normalize(iv + ivs(c))                       # times of every record of the encounter
            act = normalize(act + actual(c))
        corrected[key] -= pairs
        meta[key] = (pairs | corrected[key], iv, act)
    for c in sorted(unided, key=lambda c: c.claim_id):
        d, t, iv = c.payload["service_date"], c.payload["service_type"], ivs(c)
        act = actual(c)
        cands = [k for k, (mp, miv, _) in meta.items()
                 if (d, t) in mp and (not iv or not miv or overlaps(iv, miv))]
        disputed = False
        if not cands and t in THERAPY_TYPES and act:
            # #74: the patient cannot attend two sessions at once. A psychotherapy record whose ACTUAL contact times
            # (not a schedule) overlap those of a psychotherapy contact of another type on the same date is that
            # contact with its type disputed (the #12 alternatives then carry both readings), not a second session.
            cands = [k for k, (mp, _, mact) in meta.items()
                     if mact and overlaps(act, mact) and any(md == d and mt in THERAPY_TYPES for md, mt in mp)]
            disputed = True
        if len(cands) == 1:
            groups[cands[0]].append(c)
            mp, miv, mact = meta[cands[0]]
            if disputed:
                others = sorted({mt for md, mt in mp if md == d})
            meta[cands[0]] = (mp | {(d, t)}, normalize(miv + iv), normalize(mact + act))
            via = " (the service type a correction gives the encounter)" if (d, t) in corrected[cands[0]] else ""
            res.decide(cands[0], "R1", "matched_without_id",
                       f"{c.doc_label} names no encounter ID; matched on date {d} + service type {t}{via}"
                       if not disputed else
                       f"{c.doc_label} names no encounter ID; matched on date {d} + overlapping contact times "
                       f"{fmt_set(act)}: "
                       f"it states {t} where the contact's records state {others}, so the service type is disputed",
                       [c.claim_id])
            continue
        n = sum(1 for k in meta if k.startswith(f"{mrn}|U-{d}-{t}")) + 1
        key = f"{mrn}|U-{d}-{t}-{n}"
        groups[key].append(c)
        meta[key] = ({(d, t)}, iv, act)
        why = "ambiguous: several candidates" if cands else "no matching encounter"
        res.decide(key, "R1", "unidentified_contact", f"{c.doc_label}: {why} ({d}, {t}); kept as a separate contact",
                   [c.claim_id])
    return groups


def _corr_value(fname: str, v):
    """Comparable form of a correction or record value for one field, or None if it cannot be understood.
    Times compare by value (9:00 == 09:00), intervals by their minutes, codes by their normalised spelling."""
    if v is None:
        return None
    if fname in ("arrival", "departure"):
        return to_min(str(v))
    if fname == "contact_interval":
        if isinstance(v, dict):
            s, e = to_min(v.get("start")), to_min(v.get("end"))
        else:
            m = _INTERVAL.fullmatch(str(v))
            s, e = (to_min(m.group(1)), to_min(m.group(2))) if m else (None, None)
        return (s, e) if s is not None and e is not None and e > s else None
    code = re.sub(r"[\s-]+", "_", str(v).strip().lower())
    return code if code in (ATTENDED if fname == "disposition" else SERVICE_TYPES) else None


def _corr_display(fname: str, k):
    """A comparable value back in the record's own form (HH:MM, {start, end} or a code)."""
    if fname in ("arrival", "departure"):
        return fmt(k)
    if fname == "contact_interval":
        return {"start": fmt(k[0]), "end": fmt(k[1])}
    return k


def _corr_label(fname: str, k) -> str:
    return fmt_set([k]) if fname == "contact_interval" else str(_corr_display(fname, k))


def _reach(v0, succ: dict) -> list:
    """Values reachable from v0 (v0 first), breadth-first, each once."""
    order, seen = [v0], {v0}
    for v in order:
        for e in succ.get(v, ()):
            if e[1] not in seen:
                seen.add(e[1]); order.append(e[1])
    return order


def _resolve(v0, edges: list[tuple]) -> dict:
    """Follow corrections (old, new, claim) from v0 and return {terminal value: [the corrections that lead there]}.

    By graph reachability over a visited set, not path enumeration (#63: many restatements of a chain, or a dense
    graph, grew combinatorially). Terminals are the reachable values no correction replaces, plus every reachable
    value on a cycle, so a chain ends in the same place whatever order the claims arrive in, and competing
    corrections or a cycle leave several terminals instead of first-match-wins (#9). A terminal's corrections are
    the reachable edges from whose new value the terminal can be reached, in breadth-first order (by claim id within
    a value). `{v0: []}`: nothing corrects v0."""
    succ: dict = defaultdict(list)
    for e in sorted(edges, key=lambda e: e[2].claim_id):
        succ[e[0]].append(e)
    order = _reach(v0, succ)
    live = [e for v in order for e in succ.get(v, ())]
    if not live:
        return {v0: []}
    desc = {v: set(_reach(v, succ)) for v in order}            # v itself included
    cyclic = {v for v in order if any(v in desc[e[1]] for e in succ.get(v, ()))}
    terminals = [v for v in order if not succ.get(v) or v in cyclic]
    return {t: [e for e in live if t in desc[e[1]]] for t in terminals}


def _apply_corrections(group: list[Claim], corrections: list[Claim], key: str,
                       res: Result) -> tuple[list[str], list[Claim]]:
    """R3 field corrections, applied to every record of the encounter except the correcting document's own.

    - Chains (a -> b, then b -> c) are followed to their end, independent of claim order (#9).
    - Corrections that disagree (a -> b and a -> c), or form a cycle, keep every alternative in `c.alts`. Minutes and
      attendance then become disputed bounds, with a conflict. Nothing is picked.
    - arrival, departure, disposition, contact_interval and service_type are supported. A correction that cannot be
      applied (other field, value not understood, no record holds the old value) is a decision and a flag (#10).

    Returns (encounter flags, the correction claims that changed at least one record)."""
    for c in group:
        c.eff = {k: c.payload.get(k) for k in ("patient_arrival", "patient_departure", "disposition", "service_type",
                                               "patient_contact_intervals")}
        c.alts = {}
    flags: list[str] = []
    edges: dict[str, list[tuple]] = defaultdict(list)
    for corr in sorted(corrections, key=lambda c: c.claim_id):
        p = corr.payload
        fname = p.get("field") or ""
        old, new = _corr_value(fname, p.get("old_value")), _corr_value(fname, p.get("new_value"))
        why = (f"field '{fname or 'unspecified'}' is not a correctable field" if fname not in FIELD_MAP
               else "the original or corrected value is missing or not understood" if old is None or new is None
               else "the original and corrected values are the same" if old == new else None)
        if why:
            _not_applied(key, corr, why, flags, res)
        else:
            edges[fname].append((old, new, corr))
    used: dict[str, Claim] = {}
    reached_excluded: dict[str, set[str]] = defaultdict(set)   # correction -> excluded records it would change
    conflicts: dict[tuple, dict] = {}
    # Records that contribute (tier 1/2) first: a correction counts as applied only when it changed one of them
    # (#64). Excluded records (copies, drafts) then take the applied corrections too, so a later resend of the
    # corrected record agrees with it, but a correction that reached ONLY an excluded record is not applied.
    for c in [c for c in group if c.tier is not None] + [c for c in group if c.tier is None]:
        contributes = c.tier is not None
        for fname, fedges in sorted(edges.items()):
            f = FIELD_MAP[fname]
            if c.eff.get(f) is None:
                continue
            mine = [e for e in fedges if e[2].sha256 != c.sha256]
            if not contributes:
                for v in (c.eff[f] if fname == "contact_interval" else [c.eff[f]]):
                    k0 = _corr_value(fname, v)
                    for t, es in (_resolve(k0, mine) if k0 is not None else {}).items():
                        for e in es:
                            if e[2].claim_id not in used:
                                reached_excluded[e[2].claim_id].add(c.doc_label)
                mine = [e for e in mine if e[2].claim_id in used]
            per_value = []                         # per record value (one, or each contact interval): alternatives
            for v in (c.eff[f] if fname == "contact_interval" else [c.eff[f]]):
                k0 = _corr_value(fname, v)
                found = _resolve(k0, mine) if k0 is not None else {}
                if not found or found == {k0: []}:
                    per_value.append([v])
                    continue
                alts = sorted(found, key=str)
                path_ids = {t: {e[2].claim_id for e in found[t]} for t in alts}
                if contributes:
                    for t in alts:
                        for _, _, corr in found[t]:
                            used[corr.claim_id] = corr
                if len(alts) == 1:
                    for _, _, corr in found[alts[0]]:          # one decision per applied correction (#63)
                        res.decide(key, "R3", "field_corrected",
                                   f"{c.doc_label} {fname} {corr.payload['old_value']} replaced by "
                                   f"{corr.payload['new_value']} per explicit correction in {corr.doc_label} "
                                   "(correction applies to this field only)", [c.claim_id, corr.claim_id])
                else:
                    labels = [_corr_label(fname, t) for t in alts]
                    res.decide(key, "R3", "correction_disputed",
                               f"{c.doc_label} {fname} {_corr_label(fname, k0)}: corrections disagree "
                               f"({' vs '.join(labels)}) and none supersedes another; every alternative is kept",
                               [c.claim_id] + [i for t in alts for i in path_ids[t]])
                    entry = conflicts.setdefault((fname, tuple(labels)), {
                        "subject_key": key, "field": f"correction:{fname}", "resolution": "disputed",
                        "candidates": [{"value": x, "claim_ids": set()} for x in labels]})
                    for cand, t in zip(entry["candidates"], alts):
                        cand["claim_ids"] |= {c.claim_id} | path_ids[t]
                per_value.append([_corr_display(fname, t) for t in alts])
            combos = [list(x) for x in itertools.product(*per_value)]
            c.eff[f] = combos[0] if fname == "contact_interval" else combos[0][0]
            if len(combos) > 1:
                c.alts[f] = combos if fname == "contact_interval" else [x[0] for x in combos]
    for entry in conflicts.values():
        for cand in entry["candidates"]:
            cand["claim_ids"] = sorted(cand["claim_ids"])
        res.conflicts.append(entry)
        flags.append(f"competing corrections of {entry['field'].split(':', 1)[1]}: "
                     + " vs ".join(x["value"] for x in entry["candidates"]))
    for fname, fedges in sorted(edges.items()):
        for _, _, corr in fedges:
            if corr.claim_id in used:
                continue
            old = corr.payload.get("old_value")
            if corr.claim_id in reached_excluded:
                why = (f"{fname} {old} is held only by excluded record(s) "
                       f"{', '.join(sorted(reached_excluded[corr.claim_id]))}, which do not count for this encounter")
            else:
                why = f"no other record of this encounter has {fname} {old}"
            _not_applied(key, corr, why, flags, res)
    return flags, [used[k] for k in sorted(used)]


def _not_applied(key: str, corr: Claim, why: str, flags: list[str], res: Result) -> None:
    p = corr.payload
    flags.append(f"correction in {corr.doc_label} not applied: {why}")
    res.decide(key, "R3", "correction_not_applied",
               f"{corr.doc_label} corrects {p.get('field')} {p.get('old_value')} -> {p.get('new_value')}, but {why}",
               [corr.claim_id])


def _variants(c: Claim) -> list[dict]:
    """The record's effective values: one dict per combination of competing corrections (usually just c.eff)."""
    if not c.alts:
        return [c.eff]
    fs = sorted(c.alts)
    return [dict(c.eff, **dict(zip(fs, combo))) for combo in itertools.product(*(c.alts[f] for f in fs))]


def _covered(scopes, rid: str | None, rdate: str | None) -> bool:
    """Is a record (its encounter or form ID, and date) inside a copy relation's scope (#22)?
    - A relation naming an ID covers records with that ID, and records without an ID on one of its dates.
    - One naming only a date covers that date. One naming neither covers its whole document."""
    for sid, dates in scopes:
        if sid and rid:
            hit = sid == rid
        elif sid:
            hit = rdate in dates
        else:
            hit = not dates or rdate in dates
        if hit:
            return True
    return False


def _scopes(rels: list[Claim], id_field: str, records: list[Claim], rid_field: str, date_field: str) -> dict:
    """sha256 -> [(ID, dates)] for copy relations. A relation without a date takes the dates of the records of its
    own document that carry its ID, so an ID-less record of that date is covered too."""
    out: dict[str, list] = defaultdict(list)
    for r in rels:
        sid, d = _norm_id(r.payload.get(id_field)), r.payload.get("original_date")
        dates = {d} if d else {x.payload.get(date_field) for x in records
                               if x.sha256 == r.sha256 and sid and _norm_id(x.payload.get(rid_field)) == sid}
        out[r.sha256].append((sid, dates))
    return out


def _lines(spans) -> set[int]:
    return {n for s in spans if s.get("line_start") for n in range(s["line_start"], (s.get("line_end") or s["line_start"]) + 1)}


def _cited_corrections(group: list[Claim], applied: list[Claim]) -> list[str]:
    """Applied correction relations that join the encounter's provenance, so the passage that changed a number is in
    its evidence and can be cited (#23). A relation whose lines another claim of the same document in this encounter
    already cites adds nothing and is left out."""
    out = []
    for corr in applied:
        same = [c for c in group if c.sha256 == corr.sha256]
        if not same or not _lines(corr.evidence) <= _lines(s for c in same for s in c.evidence):
            out.append(corr.claim_id)
    return out


def _vote(values: list[str]) -> tuple[str, bool]:
    vals = set(values)
    if "yes" in vals and "no" in vals:
        return "disputed", True
    if "yes" in vals:
        return "yes", False
    if "no" in vals:
        return "no", False
    return "unknown", False


def _reconcile_encounter(key: str, group: list[Claim], corrections: list[Claim], retransmitted: dict[str, list],
                         res: Result) -> tuple[dict, list[dict]]:
    flags: list[str] = []
    group_eid = key.split("|", 1)[1]           # R1 already placed ID-less records: E1, or their own U- contact
    for c in group:
        _classify(c)
        rid = _norm_id(c.payload.get("encounter_id")) or group_eid
        if c.tier is not None and _covered(retransmitted.get(c.sha256, ()), rid, c.payload.get("service_date")):
            c.tier, c.excluded_reason = None, NOT_EVIDENCE["retransmitted_copy"]
        if c.excluded_reason:
            is_copy = c.excluded_reason == NOT_EVIDENCE["retransmitted_copy"]
            res.decide(key, "R3" if is_copy else "R2",
                       "evidence_excluded", f"{c.doc_label} ({c.evidence_type}): {c.excluded_reason}"
                       + (f"; it states disposition '{c.payload['disposition']}'" if c.payload.get("disposition") not in (None, "unknown") else ""),
                       [c.claim_id])
    corr_flags, applied = _apply_corrections(group, corrections, key, res)
    flags.extend(corr_flags)
    t1 = [c for c in group if c.tier == 1]
    t2 = [c for c in group if c.tier == 2]
    usable = t1 + t2
    ids = [c.claim_id for c in group]

    # service type and date (R4): the deciding tier (tier 1, then tier 2, then anything). A disagreement is not
    # resolved by majority or lexical order (#12): each therapy (date, type) account becomes an alternative row
    # (see _add_identity_alternatives) and eligibility becomes 'uncertain', so the dispute reaches the bounds.
    pool = t1 or t2 or group
    types = Counter(v["service_type"] for c in pool for v in _variants(c))
    stype = sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    dates = Counter(c.payload["service_date"] for c in pool)
    sdate = sorted(dates.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    accounts = sorted({(c.payload["service_date"], v["service_type"]) for c in pool for v in _variants(c)})
    therapy_accounts = [a for a in accounts if a[1] in THERAPY_TYPES]
    if len(accounts) > 1:                                  # a representative; the alternatives keep the others
        sdate, stype = (therapy_accounts or accounts)[0]   # (a psychotherapy account if there is one; never majority)
    for fld, counts in (("service_type", types), ("service_date", dates)):
        if len(counts) > 1:
            flags.append(f"{fld.replace('_', ' ')} disagreement: {dict(counts)}")
            res.conflicts.append({"subject_key": key, "field": fld, "resolution": "disputed", "candidates": [
                {"value": x, "claim_ids": [c.claim_id for c in pool if any(
                    (v["service_type"] if fld == "service_type" else c.payload[fld]) == x for v in _variants(c))]}
                for x in counts]})
    modality = next((c.payload["modality"] for c in t1 if c.payload.get("modality") not in (None, "unknown")),
                    next((c.payload["modality"] for c in usable if c.payload.get("modality") not in (None, "unknown")), "unknown"))
    eid = _norm_id(next((c.payload.get("encounter_id") for c in group if c.payload.get("encounter_id")), None))

    # attendance (R4/R5)
    attended, deciding = "unknown", []
    for tier in (t1, t2):
        vals = [ATTENDED.get(v.get("disposition") or "unknown", "unknown") for c in tier for v in _variants(c)]
        a, disputed = _vote(vals)
        if a != "unknown":
            attended, deciding = a, tier
            if disputed:
                res.conflicts.append({"subject_key": key, "field": "attendance", "resolution": "disputed",
                                      "candidates": [{"value": v, "claim_ids": [c.claim_id for c in tier if any(ATTENDED.get(x.get('disposition') or 'unknown') == v for x in _variants(c))]} for v in ("yes", "no")]})
            break
    dispositions = Counter(v.get("disposition") for c in deciding for v in _variants(c)
                           if ATTENDED.get(v.get("disposition") or "unknown") == attended)
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
    alternatives: list[tuple[str, str]] = []
    if is_therapy and eligible != "no" and len(accounts) > 1:
        disputed = " and ".join(f for f, n in (("service type", len(types)), ("service date", len(dates))) if n > 1)
        eligible = "uncertain"
        reason = (f"{disputed} disputed between equal-precedence records ("
                  + "; ".join(f"{d} {t}" for d, t in accounts) + "); "
                  + (f"{reason}; " if reason else "") + "counted only within bounds")
    if len(accounts) > 1 and attended != "no" and present != "no":
        # every other account gets its own row (#12), a non-psychotherapy one too: a goal that counts that type
        # (e.g. medication management, #48) must see it within bounds
        alternatives = [a for a in accounts if a != (sdate, stype)]
    res.decide(key, "R5", f"eligible={eligible}", reason or f"{stype}, attended, patient present", ids)

    # minutes (R6)
    rows: list[dict] = []
    # Exclusions are reconciled per kind, like any other field (#13). A record that states no exclusion of a kind
    # is silent about it (an attendance register rarely records the group break), not a "no break" account. The
    # first tier that states a kind decides it. Different sets of one kind stated by records of that tier are
    # alternative accounts, combined with every presence candidate: they are never unioned into one cumulative
    # subtraction. Different kinds (a break in the note, a disconnection in the platform log) all apply.
    stated: dict[str, dict[int, list[tuple[Claim, list]]]] = defaultdict(lambda: defaultdict(list))
    for c in usable:
        per_kind: dict[str, list] = defaultdict(list)
        for n in c.payload.get("nontherapeutic_intervals") or []:
            per_kind[n["kind"]].append((n["start"], n["end"]))
        for kind, raw in per_kind.items():
            stated[kind][c.tier].append((c, raw))
    excl: list[tuple[int, int, str, str]] = []
    bad_excl: list[str] = []
    kind_alts: list[tuple[str, list[tuple[tuple, list[Claim]]]]] = []
    for kind in sorted(stated):
        tier = min(stated[kind])
        alts: dict[tuple, list[Claim]] = defaultdict(list)
        for c, raw in stated[kind][tier]:
            valid = []
            for rs, re_ in raw:
                s, e = to_min(rs), to_min(re_)
                if s is not None and e is not None and e > s:
                    valid.append((s, e)); excl.append((s, e, kind, c.claim_id))
                else:
                    bad_excl.append(f"{c.doc_label} states a {kind} {rs}–{re_} that is not a valid same-day interval "
                                    "(overnight, inverted or incomplete); its length is unknown")
            alts[tuple(normalize(valid))].append(c)
        kind_alts.append((kind, list(alts.items())))
        for other in sorted(t for t in stated[kind] if t != tier):
            res.decide(key, "R4", "exclusion_tier",
                       f"{', '.join(sorted({c.doc_label for c, _ in stated[kind][other]}))} (tier {other}) also state(s) "
                       f"a {kind}; the tier-{tier} records decide it", [c.claim_id for c, _ in stated[kind][other]])
    accts: list[tuple[tuple, list[Claim]]] = [((), [])]    # (exclusion intervals (s, e, kind), stating records)
    for kind, alts_k in kind_alts:
        accts = [(items + tuple((s, e, kind) for s, e in ivs_k), cl + cs) for items, cl in accts for ivs_k, cs in alts_k]
    acct_ivs = [normalize([(s, e) for s, e, _ in items]) for items, _ in accts]
    for s, e, kind, cid in sorted(set(excl)):
        rows.append({"encounter_key": key, "kind": "excluded", "start_min": s, "end_min": e, "label": kind,
                     "claim_ids": [cid]})
    # The scheduled interval is reconciled like any other account (#66), not taken from the first record: the first
    # tier that states a schedule decides it; records of that tier that disagree are alternatives (a conflict), and
    # every one of them reaches the bounds below. A lower tier's different schedule is logged, not used.
    sched_by: dict[tuple, list[Claim]] = {}
    for c in usable:
        sc = c.payload.get("scheduled")
        k = (to_min(sc.get("start")), to_min(sc.get("end"))) if sc else None
        if k and None not in k:
            sched_by.setdefault(k, []).append(c)
    for k, cs in sched_by.items():
        rows.append({"encounter_key": key, "kind": "scheduled", "start_min": k[0], "end_min": k[1],
                     "label": "scheduled", "claim_ids": [c.claim_id for c in cs]})
    s_tier = min((c.tier for cs in sched_by.values() for c in cs), default=None)
    deciding_sched = {k: [c for c in cs if c.tier == s_tier] for k, cs in sched_by.items()}
    deciding_sched = {k: cs for k, cs in deciding_sched.items() if cs}
    scheds = sorted(k for k in deciding_sched if k[1] > k[0])           # valid same-day schedules
    lower = [c for k, cs in sched_by.items() if k not in deciding_sched for c in cs]
    if lower:
        res.decide(key, "R4", "schedule_tier",
                   f"{', '.join(sorted({c.doc_label for c in lower}))} (tier {s_tier + 1}) state(s) a different "
                   f"schedule; the tier-{s_tier} records decide it "
                   f"({', '.join(fmt_set([k]) for k in sorted(deciding_sched))})", [c.claim_id for c in lower])
    if len(deciding_sched) > 1:
        flags.append("scheduled interval disagreement: " + " vs ".join(
            f"{fmt_set([k])} ({', '.join(sorted({c.doc_label for c in cs}))})" for k, cs in sorted(deciding_sched.items())))
        res.conflicts.append({"subject_key": key, "field": "scheduled_interval", "resolution": "disputed",
                              "candidates": [{"value": fmt_set([k]), "claim_ids": [c.claim_id for c in cs]}
                                             for k, cs in sorted(deciding_sched.items())]})
    # Same-day interval algebra cannot represent an interval that crosses midnight or is inverted (#17). Such an
    # interval is never silently dropped (that turned an overnight session into an established 0): the minutes
    # become unknown, with no upper bound unless a valid schedule gives one, and the interval is flagged.
    bad_presence: list[str] = []
    bad_scheds = [f"scheduled {fmt_set([k])} is not a valid same-day interval (overnight or inverted)"
                  for k in sorted(deciding_sched) if not k[1] > k[0]]
    sched_ok = bool(scheds) and not bad_scheds

    cands: dict[tuple, list[Claim]] = defaultdict(list)
    basis: dict[tuple, str] = {}
    for c, v in ((c, v) for c in t1 for v in _variants(c)):
        raw = [(i["start"], i["end"]) for i in v.get("patient_contact_intervals") or []]
        raw_min = [(to_min(s), to_min(e)) for s, e in raw]
        bad = [f"{s}–{e}" for (s, e), (ms, me) in zip(raw, raw_min) if ms is None or me is None or me <= ms]
        if bad:
            msg = (f"{c.doc_label} states contact interval(s) {', '.join(bad)} that are not valid same-day intervals "
                   "(overnight, inverted or incomplete)")
            if msg not in bad_presence:
                bad_presence.append(msg)
            continue
        ci = normalize(raw_min)
        if ci:
            _add_cand(cands, tuple(ci), c); basis.setdefault(tuple(ci), "stated contact intervals")
            continue
        a, d = to_min(v.get("patient_arrival")), to_min(v.get("patient_departure"))
        if a is not None and d is not None and d > a:
            _add_cand(cands, ((a, d),), c); basis.setdefault(((a, d),), "arrival–departure")
        elif a is not None and d is not None:
            msg = (f"{c.doc_label} arrival {v.get('patient_arrival')} is not before departure "
                   f"{v.get('patient_departure')} (overnight or inverted)")
            if msg not in bad_presence:
                bad_presence.append(msg)
    full = [c for c in t1 if c.eff.get("disposition") == "attended_full"]
    if not cands and not bad_presence and full and bad_scheds:
        bad_presence += bad_scheds                         # a schedule would have been the presence account
    elif not cands and sched_ok and full:
        for c in full:                                     # its own schedule, else every deciding schedule (#66)
            sc = c.payload.get("scheduled") or {}
            own = (to_min(sc.get("start")), to_min(sc.get("end")))
            for k in ([own] if own in scheds else scheds):
                _add_cand(cands, (k,), c)
                basis[(k,)] = "attended full scheduled session"
    flags += [m for m in bad_scheds if m not in bad_presence] + bad_presence + bad_excl

    m_low = m_high = None
    calc = None
    if eligible == "no" and not is_therapy:
        status = "not_applicable"
    elif eligible == "no":
        status, m_low, m_high = "not_applicable", 0, 0
    elif cands and not bad_presence:
        mins: dict[tuple, int] = {}                        # (presence candidate, exclusion account) -> minutes
        for iv, cs in cands.items():
            for ai, a_ivs in enumerate(acct_ivs):
                mins[(iv, ai)] = total(subtract(list(iv), a_ivs))
            rows.append({"encounter_key": key, "kind": "present", "start_min": iv[0][0], "end_min": iv[-1][1],
                         "label": f"{basis[iv]}: {fmt_set(list(iv))} per {', '.join(sorted({x.doc_label for x in cs}))}",
                         "claim_ids": [x.claim_id for x in cs]})
        m_low, m_high = min(mins.values()), max(mins.values())
        parts = []
        for (iv, ai), m in sorted(mins.items(), key=lambda kv: kv[1]):
            cs = cands[iv]
            ex = [f"{k} {fmt_set([(s, e)])}" for s, e, k in sorted(set(accts[ai][0]))]
            src = (f" [exclusions per {', '.join(sorted({x.doc_label for x in accts[ai][1]})) or 'no record'}]"
                   if len(accts) > 1 else "")
            parts.append(f"{fmt_set(list(iv))} ({basis[iv]}; {', '.join(sorted({x.doc_label for x in cs}))})"
                         + (f" − {' − '.join(ex)}" if ex and total(list(iv)) != m else "") + src + f" = {m} min")
        calc = " | ".join(parts)
        if len(cands) > 1:
            what = ("scheduled intervals for an attended-full session" if all(
                basis[iv] == "attended full scheduled session" for iv in cands) else "patient-contact intervals")
            res.conflicts.append({"subject_key": key, "field": "patient_present_interval", "resolution": "disputed",
                                  "candidates": [{"value": fmt_set(list(iv)),
                                                  "minutes": mins[(iv, 0)] if len(accts) == 1
                                                  else sorted({mins[(iv, ai)] for ai in range(len(accts))}),
                                                  "claim_ids": [x.claim_id for x in cs]} for iv, cs in cands.items()]})
            res.decide(key, "R4", "minutes_disputed",
                       f"tier-1 records give different {what} and none corrects the other: " + calc
                       + f"; carried as bounds [{m_low}, {m_high}]", [x.claim_id for cs in cands.values() for x in cs])
        if len(accts) > 1:
            split = [(k, a) for k, a in kind_alts if len(a) > 1]
            res.conflicts.append({"subject_key": key, "field": "nontherapeutic_intervals", "resolution": "disputed",
                                  "candidates": [{"kind": k, "value": fmt_set(list(ivs_k)),
                                                  "claim_ids": [x.claim_id for x in cs]}
                                                 for k, a in split for ivs_k, cs in a]})
            res.decide(key, "R6", "exclusions_disputed",
                       f"records state different {'/'.join(k for k, _ in split)} intervals and none corrects the "
                       "other; each account is applied on its own, never summed: " + calc
                       + f"; carried as bounds [{m_low}, {m_high}]", [x.claim_id for _, a in split for _, cs in a for x in cs])
        status = "disputed" if len(cands) > 1 or len(accts) > 1 else "established"
        if bad_excl:
            status, m_low = "unknown", 0
            calc += f"; lower bound 0 because {'; '.join(bad_excl)}"
            res.decide(key, "R6", "minutes_unknown", calc, ids)
        # stated-minute cross-check (R6)
        for c in t1:
            sm = c.payload.get("stated_minutes")
            if sm is not None and not (m_low <= sm <= m_high):
                flags.append(f"{c.doc_label} states {sm} min; patient-present computation gives "
                             f"{m_low if m_low == m_high else f'{m_low}–{m_high}'} min")
    else:
        status = "unknown"
        m_low = 0
        m_high = (max(total(subtract([k], a)) for k in scheds for a in acct_ivs)   # largest schedule, least
                  if sched_ok else None)                                          # subtraction (#66)
        if m_high is not None and cands:                   # valid accounts beside an invalid one (#17)
            m_high = max([m_high] + [total(subtract(list(iv), a)) for iv in cands for a in acct_ivs])
        calc = ("no patient arrival/departure or contact interval documented; bounds 0.." if not bad_presence else
                f"patient-present time cannot be computed ({'; '.join(bad_presence)}); bounds 0..")
        calc += (f"{m_high} (scheduled {' / '.join(fmt_set([k]) for k in scheds)} minus exclusions)"
                 if m_high is not None else "unbounded")
        res.decide(key, "R6", "minutes_unknown", calc, ids)
    if calc and status == "established":
        res.decide(key, "R6", f"minutes={m_low}", calc, [x.claim_id for cs in cands.values() for x in cs]
                   + [cid for *_, cid in excl])

    enc = {
        "encounter_key": key, "mrn": res.mrn, "encounter_id": eid, "service_date": sdate, "service_type": stype,
        "modality": modality, "disposition": disposition, "attended": attended, "patient_present": present,
        "is_therapy": int(is_therapy), "eligible": eligible, "exclusion_reason": reason,
        "minutes_low": m_low, "minutes_high": m_high, "minutes_status": status, "calculation": calc,
        "claim_ids": sorted(ids + _cited_corrections(group, applied)), "flags": flags, "ruleset_version": RULESET_VERSION,
        "_present_sets": [list(iv) for iv in cands] if eligible != "no" else [],
        "_superseded": [], "_identity": key, "_alternatives": alternatives,
    }
    # remember pre-correction presence for the overlap rationale
    for c in t1:
        a, d = to_min(c.payload.get("patient_arrival")), to_min(c.payload.get("patient_departure"))
        ea, ed = to_min(c.eff.get("patient_arrival")), to_min(c.eff.get("patient_departure"))
        if (a, d) != (ea, ed) and a is not None and d is not None and not ({"patient_arrival", "patient_departure"} & set(c.alts)):
            enc["_superseded"].append(((a, d), c.doc_label))
    return enc, rows


def _add_cand(cands: dict, k: tuple, c: Claim) -> None:
    if all(x is not c for x in cands[k]):           # one record may reach the same set through several variants
        cands[k].append(c)


def _add_identity_alternatives(encs: list[dict], res: Result) -> list[dict]:
    """Alternative rows of encounters whose service date or type is disputed between equal-precedence records
    (#12). One row carries one date and one type, so each further (date, type) account becomes its own row (key
    `<encounter key>~<date>-<type>`, same intervals; 'uncertain' for psychotherapy, 'no' for any other type, which
    only a goal counting that type sees, #48), and the dispute reaches the bounds of
    every week and every per-type goal it could belong to. The rows share `encounter_id`; `project.aggregate` counts
    them as at most one session (and the larger of their minutes), so they never add up to more than the single
    encounter they are. R7 does not compare them with each other (same `_identity`)."""
    out = []
    for enc in encs:
        out.append(enc)
        rows = [r for r in res.intervals if r["encounter_key"] == enc["encounter_key"]] if enc["_alternatives"] else []
        for d, t in enc["_alternatives"]:
            k = f"{enc['encounter_key']}~{d}-{t}"
            # a non-psychotherapy account is never an eligible session (R5); it exists for goals counting its type
            other = {} if t in THERAPY_TYPES else {
                "is_therapy": 0, "eligible": "no", "exclusion_reason": f"not a psychotherapy service ({t})",
                "minutes_low": None, "minutes_high": None, "minutes_status": "not_applicable", "calculation": None,
                "_present_sets": []}
            out.append({**enc, "encounter_key": k, "service_date": d, "service_type": t,
                        "flags": enc["flags"] + [f"alternative identity of {enc['encounter_key']} ({enc['service_date']} "
                                                 f"{enc['service_type']}): service date/type disputed"],
                        "_superseded": [], "_alternatives": [], **other})
            res.intervals.extend({**r, "encounter_key": k} for r in rows)
            res.decide(k, "R1", "identity_alternative",
                       f"records of {enc['encounter_key']} disagree on its service date/type; this row is the {d} {t} "
                       "account and counts within bounds only (at most one session with its alternatives)",
                       enc["claim_ids"])
    return out


def _overlap_checks(encs: list[dict], res: Result) -> None:
    by_date = defaultdict(list)
    for e in encs:
        by_date[e["service_date"]].append(e)
    for d, es in by_date.items():
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                if a["_identity"] == b["_identity"]:      # alternative rows of one encounter (#12), not two contacts
                    continue
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
    _goals_not_restated(res)


def _goals_not_restated(res: Result) -> None:
    """R9 note (#49): a later requirement for the same metric that does not restate an earlier goal (same metric,
    counted types and period) leaves it unclear whether that goal lapsed. Nothing in the record says the revision
    replaces the whole plan, so the projection evaluates both possibilities (`project.requirement_sets_on`); this
    decision makes that visible once per goal, at the first revision that omits it."""
    def gk(p):
        return (p["metric"], tuple(p["counted_types"]), p["period"])

    for p in res.plans:
        start, end = p["effective_start"] or "", p["effective_end"]
        later = sorted({q["effective_start"] or "" for q in res.plans
                        if q["metric"] == p["metric"] and gk(q) != gk(p) and (q["effective_start"] or "") > start
                        and (end is None or (q["effective_start"] or "") <= end)})
        for d in later:
            if any(gk(q) == gk(p) and start < (q["effective_start"] or "") <= d for q in res.plans):
                break                                   # restated (superseded) before this revision: not lapsing
            rev = [q for q in res.plans if q["metric"] == p["metric"] and (q["effective_start"] or "") == d]
            res.decide(p["requirement_key"], "R9", "goal_not_restated",
                       f"{p['doc_label']}'s {p['metric']} {p['comparator']} {p['threshold']:g} goal over "
                       f"{p['counted_types']} ({p['period']}, effective {p['effective_start']}) is not restated by "
                       f"{', '.join(sorted({q['doc_label'] for q in rev}))} (effective {d}), which revises "
                       f"{p['metric']}; from {d} it may have lapsed or may continue, so it is evaluated both ways",
                       p["claim_ids"] + [i for q in rev for i in q["claim_ids"]])
            break


def _assessments(acl: list[Claim], copy_docs: dict[str, list], res: Result) -> None:
    groups: dict[tuple, list[Claim]] = defaultdict(list)
    for c in acl:
        p = c.payload
        groups[(p["instrument"].upper().replace(" ", ""), p.get("completed_date"))].append(c)
    for (inst, d), cs in sorted(groups.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
        forms = sorted({c.payload.get("form_id") for c in cs if c.payload.get("form_id")})
        buckets = {f: [c for c in cs if c.payload.get("form_id") in (f, None)] for f in forms} if len(forms) > 1 else {forms[0] if forms else None: cs}
        for form, bcs in buckets.items():
            copies = [c for c in bcs if c.payload.get("is_copy_of_earlier") or _covered(
                copy_docs.get(c.sha256, ()), _norm_id(c.payload.get("form_id")), c.payload.get("completed_date"))]
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

def _rejection_reason(c: Claim) -> str:
    """Why ingest left a claim unverified, from its evidence (#68). A date that is stated nowhere in the document
    (#52) is named as such: its quote WAS found, so "quote not found" would be false. A located quote failure keeps
    the generic text. The inferred value itself is not repeated: it must not reach results as if it were a date
    of the record."""
    grounding = next((s for s in reversed(c.evidence or []) if s.get("match") == "grounding"), {})
    absent = grounding.get("unverified_absent") or []
    why = []
    if any(s.get("match") == "missing" for s in c.evidence or []) or not absent:
        why.append("quote not found in source text")
    why += [f"the {f.replace('_', ' ')} is not stated anywhere in the document (the extracted value was inferred)"
            for f in absent]
    return "; ".join(why)


def reconcile_patient(mrn: str, claims: list[Claim]) -> Result:
    # One canonical order (claim id, the order `load_claims` reads), so every decision reason, flag, conflict and
    # first-record choice is a function of the claim SET, not of the order a caller passes it in (#62).
    claims = sorted(claims, key=lambda c: c.claim_id)
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
                       f"{c.doc_label} {c.kind}: {_rejection_reason(c)}", [c.claim_id])
    claims = [c for c in claims if c.verified or c.kind == "document"]
    rel = [c for c in claims if c.kind == "relation"]
    corrections = defaultdict(list)
    for r in rel:
        t, eid = r.payload["type"], _norm_id(r.payload.get("encounter_id"))
        if t == "corrects_field" and eid:
            corrections[f"{mrn}|{eid}"].append(r)
        elif t == "corrects_field":
            res.decide(r.subject_key or r.doc_label, "R3", "correction_not_applied",
                       f"{r.doc_label} corrects {r.payload.get('field')} {r.payload.get('old_value')} -> "
                       f"{r.payload.get('new_value')}, but names no encounter, so it cannot be applied", [r.claim_id])

    events = [c for c in claims if c.kind == "service_event" and c.payload.get("service_date")]
    acl = [c for c in claims if c.kind == "assessment"]
    # copy relations are scoped to the records they name, not their whole document (#22)
    retransmitted = _scopes([r for r in rel if r.payload["type"] == "retransmits_original"], "encounter_id",
                            events, "encounter_id", "service_date")
    copy_docs = _scopes([r for r in rel if r.payload["type"] == "copies_measurement"], "form_id",
                        acl, "form_id", "completed_date")
    groups = _group_events(events, res, corrections)
    encs = []
    for key in sorted(groups):
        enc, rows = _reconcile_encounter(key, groups[key], corrections.get(key, []), retransmitted, res)
        encs.append(enc)
        res.intervals.extend(rows)
    for key in sorted(set(corrections) - set(groups)):
        for r in corrections[key]:
            res.decide(key, "R3", "correction_not_applied",
                       f"{r.doc_label} corrects {r.payload.get('field')} of an encounter that has no service record",
                       [r.claim_id])
    encs = _add_identity_alternatives(encs, res)
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
    _assessments(acl, copy_docs, res)
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


def _attribution_decisions(conn: sqlite3.Connection, res: Result, claims: list[Claim]) -> None:
    """R1 provenance for documents attributed to the patient on a basis other than the extracted MRN (#71): the
    text's printed MRN (#55) or another document's recorded MRN correction (#53). `attribution_notes` is
    evidence-layer bookkeeping written by ingest; a database without it has no such documents."""
    try:
        notes = conn.execute("SELECT a.sha256, a.basis, a.reason, d.doc_label FROM attribution_notes a "
                             "JOIN documents d ON d.sha256 = a.sha256 WHERE a.mrn = ? ORDER BY d.doc_label, a.sha256",
                             (res.mrn,)).fetchall()
    except sqlite3.OperationalError:
        return
    for sha, basis, reason, label in notes:
        res.decide(f"{res.mrn}|attribution|{label}", "R1", f"attributed_by_{basis}",
                   f"{label} is attributed to {res.mrn} by {basis.replace('_', ' ')}: {reason}",
                   [c.claim_id for c in claims if c.sha256 == sha])


def reconcile_patients(conn: sqlite3.Connection, mrns) -> dict:
    out = {}
    for mrn in sorted(set(mrns)):
        claims = load_claims(conn, mrn)
        res = reconcile_patient(mrn, claims)
        _attribution_decisions(conn, res, claims)
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
