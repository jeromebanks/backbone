"""Builders for hand-made claims so reconciliation rules can be tested without any LLM."""
from __future__ import annotations

import itertools

from backbone.reconcile import Claim

_n = itertools.count()


def doc(label: str, *, signed=True, finality="final", signed_at=None, sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    return Claim(f"{sha}:document:0", sha, label, "document", label, None,
                 {"signed": signed, "finality": finality, "signed_at": signed_at, "received_at": None,
                  "patient_mrn": "P1", "title": label}, [], True)


def event(label: str, *, eid="E1", date="2026-02-02", stype="group_therapy", etype="clinical_note",
          disposition="attended", present="yes", scheduled=None, arrival=None, departure=None, contact=(),
          nontherapeutic=(), stated=None, verified=True, sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    i = next(_n)
    payload = {
        "encounter_id": eid, "related_encounter_id": None, "appointment_id": None, "service_date": date,
        "service_type": stype, "modality": "in_person", "evidence_type": etype, "disposition": disposition,
        "patient_present": present,
        "scheduled": {"start": scheduled[0], "end": scheduled[1]} if scheduled else None,
        "patient_arrival": arrival, "patient_departure": departure,
        "patient_contact_intervals": [{"start": s, "end": e} for s, e in contact],
        "nontherapeutic_intervals": [{"start": s, "end": e, "kind": k, "quote": "q"} for s, e, k in nontherapeutic],
        "stated_minutes": stated, "clinicians": [], "quotes": ["q"],
    }
    return Claim(f"{sha}:service_event:{i}", sha, label, "service_event", eid, etype, payload, [], verified)


def relation(label: str, rtype: str, *, eid=None, field=None, old=None, new=None, form_id=None, sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    i = next(_n)
    return Claim(f"{sha}:relation:{i}", sha, label, "relation", eid or form_id, None,
                 {"type": rtype, "encounter_id": eid, "field": field, "old_value": old, "new_value": new,
                  "form_id": form_id, "original_date": None, "quote": "q"}, [], True)


def assessment(label: str, *, score, date, form_id=None, copy=False, sha=None) -> Claim:
    sha = sha or f"sha-{label}"
    i = next(_n)
    return Claim(f"{sha}:assessment:{i}", sha, label, "assessment", form_id, None,
                 {"instrument": "PHQ-9", "total_score": score, "item_scores": [], "completed_date": date,
                  "completed_time": None, "form_id": form_id, "is_copy_of_earlier": copy, "quote": "q"}, [], True)


def with_docs(*claims: Claim) -> list[Claim]:
    """Add a document claim for every document referenced, so finality/signature is known."""
    out = list(claims)
    seen = {c.sha256 for c in claims if c.kind == "document"}
    for c in claims:
        if c.sha256 not in seen:
            out.append(doc(c.doc_label, sha=c.sha256))
            seen.add(c.sha256)
    return out


def enc(res, eid="E1"):
    return next(e for e in res.encounters if e["encounter_key"].endswith("|" + eid))
