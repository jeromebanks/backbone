"""Ingest documents: hash -> dedupe -> extract (cached) -> attribute to a patient -> verified claims.

Returns the set of patient MRNs whose evidence changed (new owners and former owners of re-extracted or re-attributed
documents), so only those patients are re-reconciled. They are also recorded in `pending_reconcile` in the claims'
transaction, so a crash before reconciliation is repaired by the next run. A document that cannot be attributed to
exactly one patient, or whose extracted MRN contradicts its text, is quarantined: its claims are stored with no patient
and take part in no patient's reconciliation until a later ingest can attribute it from the stored extraction.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import EXTRACTOR_VERSION
from .evidence import DocumentIndex, ground_values, times_in
from .extract import extract_document
from .llm import DEFAULT_MODEL
from .schema import Extraction

HEADER_ID = re.compile(r"^\s*Document ID:\s*(\S+)", re.MULTILINE)
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-"})
_VAL = r"[A-Za-z0-9-]*[0-9][A-Za-z0-9-]*"
# A labelled MRN value ("MRN HG-1", "MRN: hg-1", "MRN #HG-1"); the value must contain a digit so prose isn't matched.
MRN_LABEL = re.compile(r"\bMRN\b[ \t:#]*(" + _VAL + ")")
# Explicit MRN corrections on one line: "MRN X corrected/changed/updated to [MRN] Y" and "Corrected MRN Y (previously
# MRN X)". Anything looser stays a second MRN, so the document is quarantined rather than guessed at.
_CORRECTED_TO = re.compile(r"\bMRN\b[ \t:#]*(?P<old>" + _VAL + r")[^\n]{0,40}?\b(?:corrected|changed|updated|amended|"
                           r"revised|replaced)\s+(?:to|with|by)\b[ \t:#]*(?:MRN\b[ \t:#]*)?(?P<new>" + _VAL + ")", re.I)
_CORRECTED_FROM = re.compile(r"\b(?:corrected|updated|amended|revised|new|current)\s+MRN\b[ \t:#]*(?P<new>" + _VAL +
                             r")[^\n]{0,40}?\b(?:previously|formerly|replaces|replacing|was|old|prior)\b[^\n]{0,20}?"
                             r"\bMRN\b[ \t:#]*(?P<old>" + _VAL + ")", re.I)
_ISO_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
# Table header cells (exact, case-insensitive) naming a per-row patient identity. A patient banner line such as
# "Patient: A | DOB: … | MRN: …" has no such cell, and "Patient arrived" is not one either.
_MRN_HEADERS = {"mrn", "mrn #", "mrn#", "mrn no", "mrn no.", "patient mrn", "medical record number", "medical record no.",
                "medical record #"}
_NAME_HEADERS = {"patient", "patient name", "name", "member", "member name", "client", "client name", "participant",
                 "participant name", "attendee"}
_ID_TOKEN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# A whitespace-aligned table (no pipes or tabs) is recognised only when every header cell is a known column heading,
# so an aligned key/value block ("Patient      Alex Doe") is not mistaken for one (#54).
_COLUMN_HEADERS = _MRN_HEADERS | _NAME_HEADERS | {
    "status", "arrived", "departed", "arrival", "departure", "time in", "time out", "in", "out", "attended",
    "attendance", "dob", "date of birth", "notes", "note", "minutes", "present", "check-in", "check-out", "signature",
    "date", "time", "encounter", "role", "comments", "sign-in", "sign-out", "desk status", "disposition"}
# Free-text lists of the patients at a contact (#54). "Participants:" and "Present:" are deliberately not included:
# family and staff are listed there (the supplied corpus has "Participants: <patient> and <partner>").
_ATTENDEE_LINE = re.compile(r"^\s*(?:attendees|attendance|in attendance|patients(?:\s+(?:present|attending|in attendance))?"
                            r"|(?:group\s+)?members(?:\s+present)?|clients(?:\s+present)?|group (?:attendees|participants))"
                            r"\s*:\s*(.+)$", re.I | re.M)
_PERSON = re.compile(r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3}")
_CREDENTIAL = re.compile(r"[A-Z][A-Za-z]{0,4}[A-Z]")       # LCSW, MD, PhD, RN, PsyD, LMFT
_ROLE_WORDS = re.compile(r"\b(?:partner|spouse|wife|husband|mother|father|mom|dad|parent|guardian|sibling|sister|"
                         r"brother|son|daughter|friend|family|relative|clinician|therapist|facilitator|co-facilitator|"
                         r"counsel+or|social worker|staff|nurse|psychiatrist|physician|interpreter|observer|student|"
                         r"intern|supervisor|provider|case manager|caregiver)\b", re.I)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_mrn(mrn: str | None) -> str | None:
    if not mrn:
        return None
    return re.sub(r"\s+", "", mrn).upper()


def _canon(mrn: str) -> str:
    """Comparison key for identifiers: case, dashes and spacing do not distinguish two MRNs."""
    return re.sub(r"[^A-Z0-9]", "", mrn.translate(_DASHES).upper())


def mrns_in_text(text: str) -> set[str]:
    """Distinct normalised MRN values labelled in the raw document text (deterministic multi-patient guard)."""
    return {norm_mrn(m.strip("-")) for m in MRN_LABEL.findall(text.translate(_DASHES)) if m.strip("-")}


@dataclass
class TextIdentity:
    """Patient identifiers the document text itself states (no LLM involved)."""
    labelled: set[str]                                   # values after an "MRN" label
    table_mrns: set[str]                                 # values in an MRN column of a table
    corrections: list[tuple[str, str, str, int]]         # (old, new, quote, line) explicit MRN corrections
    roster_names: set[str] = field(default_factory=set)  # distinct names in a patient-name column, when >= 2
    attendee_names: set[str] = field(default_factory=set)  # distinct patient names in an attendee line, when >= 2

    @property
    def mrns(self) -> set[str]:
        """The distinct patients the text names by MRN; an MRN corrected to another is the same patient."""
        old = {o for o, *_ in self.corrections}
        return (self.labelled | self.table_mrns | {n for _, n, *_ in self.corrections}) - old


def _cells(line: str) -> tuple[str | None, list[str]]:
    for sep in ("|", "\t"):
        if sep in line:
            cells = [c.strip() for c in line.strip().strip("|").split(sep)]
            if len(cells) >= 2:
                return sep, cells
            return None, []
    cells = re.split(r" {2,}", line.strip())           # whitespace-aligned columns (#54); only without | or tab
    return ("  ", cells) if len(cells) >= 2 else (None, [])


def _table_identities(lines: list[str]) -> tuple[set[str], set[str]]:
    """MRNs and names listed under an MRN / patient-name column header, one table row per line."""
    mrns: set[str] = set()
    names: set[str] = set()
    for i, line in enumerate(lines):
        sep, head = _cells(line)
        keys = [" ".join(c.lower().split()).rstrip(":") for c in head]
        col_m = [j for j, k in enumerate(keys) if k in _MRN_HEADERS]
        col_n = [j for j, k in enumerate(keys) if k in _NAME_HEADERS]
        if not (col_m or col_n):
            continue
        if sep == "  " and not all(k in _COLUMN_HEADERS for k in keys):
            continue                                             # an aligned key/value block, not a table header
        for row in lines[i + 1:]:
            s, cells = _cells(row)
            if s != sep or len(cells) != len(head):
                break
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue                                         # markdown separator row
            mrns |= {norm_mrn(cells[j]) for j in col_m if re.search(r"\d", cells[j])}
            names |= {" ".join(cells[j].lower().split()) for j in col_n if cells[j] and cells[j] not in "-—"}
    return mrns, names


def text_identity(text: str) -> TextIdentity:
    t = text.translate(_DASHES)
    corrections = []
    for rx in (_CORRECTED_TO, _CORRECTED_FROM):
        for m in rx.finditer(t):
            old, new = norm_mrn(m["old"].strip("-")), norm_mrn(m["new"].strip("-"))
            if old and new and _canon(old) != _canon(new) and not (_ISO_DATE.fullmatch(old) or _ISO_DATE.fullmatch(new)):
                corrections.append((old, new, m.group(0), t.count("\n", 0, m.start()) + 1))
    table_mrns, names = _table_identities(t.splitlines())
    attendees = _attendee_names(t)
    return TextIdentity(mrns_in_text(t), table_mrns, sorted(set(corrections)), names if len(names) > 1 else set(),
                        attendees if len(attendees) > 1 else set())


def _attendee_names(text: str) -> set[str]:
    """Distinct person names in a free-text attendee list ("Attendees: A, B and C") that are not annotated as staff
    or family: a credential ("Mira Patel, LCSW") or a role or relation ("Casey Doe (partner)") marks the preceding
    name as not a patient (#54)."""
    out: set[str] = set()
    for m in _ATTENDEE_LINE.finditer(text):
        people: list[list] = []                          # [name, is_patient]
        for item in re.split(r"[;,]|\s+(?:and|&)\s+", m.group(1)):
            notes = re.findall(r"\(([^)]*)\)", item)
            item = re.sub(r"\([^)]*\)", " ", item).strip(" .:")
            if _PERSON.fullmatch(item):
                people.append([" ".join(item.lower().split()), True])
                note_items = notes
            else:
                note_items = notes + ([item] if item else [])
            for n in note_items:
                if people and (_CREDENTIAL.fullmatch(n.strip(" .")) or _ROLE_WORDS.search(n)):
                    people[-1][1] = False
        out |= {n for n, is_patient in people if is_patient}
    return out


def _mismatch(reason: str, candidates) -> tuple[None, dict]:
    return None, {"status": "mrn_mismatch", "candidates": sorted(set(candidates)), "reason": reason}


def resolve_identifier(conn: sqlite3.Connection, mrn: str) -> tuple[str | None, list[tuple], list[str]]:
    """Follow the explicit MRN corrections recorded from documents' text (#53): (final MRN, the steps taken as
    (old, new, doc_label, line), conflict candidates). Chains X->Y->Z are followed. A fork (X->Y and X->Z) or a cycle
    (X->Y, Y->X) resolves nothing: (None, steps so far, the candidate MRNs)."""
    edges: dict[str, dict[str, tuple]] = {}
    for r in conn.execute("SELECT c.old_mrn, c.new_mrn, d.doc_label, c.line FROM identifier_changes c "
                          "JOIN documents d ON d.sha256 = c.sha256 ORDER BY c.new_mrn, d.doc_label, c.line"):
        edges.setdefault(_canon(r[0]), {}).setdefault(_canon(r[1]), (r[0], r[1], r[2], r[3]))
    cur, steps, seen = mrn, [], [_canon(mrn)]
    while _canon(cur) in edges:
        out = edges[_canon(cur)]
        if len(out) > 1:
            return None, steps, sorted(e[1] for e in out.values())
        step = next(iter(out.values()))
        if _canon(step[1]) in seen:
            return None, steps + [step], sorted({mrn, *(s[1] for s in steps), step[1]})
        steps.append(step)
        seen.append(_canon(step[1]))
        cur = step[1]
    return cur, steps, []


def attribute_document(conn: sqlite3.Connection, text: str, ex: Extraction
                       ) -> tuple[str | None, dict | None, dict | None]:
    """Decide which patient a document belongs to: (mrn, None, note) or (None, quarantine record, None). `note` is
    {basis, reason} when the identity did not come straight from the extracted MRN (or a name match), else None.

    Never invents an identity merge: without an MRN the document must match exactly one known patient by name (and DOB
    when stated), or print exactly one MRN when the name matches no known patient (#55). The extraction holds one
    patient per document, so text naming several patients (labelled MRNs, an MRN or patient-name table column, an
    attendee list) is not attributed at all. The text outranks the extractor on identifiers: an extracted MRN must be
    the one the text prints (or, when none is labelled, appear in the text verbatim), and an explicit "MRN X corrected
    to Y" in the text attributes the document to Y. Corrections recorded from other documents then apply too (#53).
    """
    ident = text_identity(text)
    printed = sorted(ident.mrns)
    if len(printed) > 1:
        return None, {"status": "multi_patient", "candidates": printed,
                      "reason": f"document text names {len(printed)} distinct MRNs; extraction holds one patient "
                                "per document, so its claims cannot be attributed"}, None
    if ident.roster_names:
        return None, {"status": "multi_patient", "candidates": [],
                      "reason": f"a patient-name table column lists {len(ident.roster_names)} distinct names; "
                                "extraction holds one patient per document, so its claims cannot be attributed"}, None
    if ident.attendee_names:
        return None, {"status": "multi_patient", "candidates": [],
                      "reason": f"an attendee list names {len(ident.attendee_names)} distinct people not marked as "
                                "staff or family; extraction holds one patient per document, so its claims cannot be "
                                "attributed"}, None

    def finish(base: str, note: dict | None = None):
        final, steps, conflict = resolve_identifier(conn, base)
        if conflict:
            via = "; ".join(f"{o} -> {n} ({d} L{ln})" for o, n, d, ln in steps)
            return None, {"status": "ambiguous_patient", "candidates": conflict,
                          "reason": f"MRN {base} has conflicting recorded MRN corrections (a fork or a cycle) among "
                                    f"{', '.join(conflict)}" + (f"; followed {via}" if via else "")}, None
        if steps:
            via = "; ".join(f"{o} corrected to {n} by {d} L{ln}" for o, n, d, ln in steps)
            note = {"basis": "identifier_change",
                    "reason": f"document carries MRN {base}; attributed to {final} by recorded corrections: {via}"
                              + (f" (identity: {note['reason']})" if note else "")}
        return final, None, note

    corrected = {_canon(o): n for o, n, *_ in ident.corrections}
    mrn = norm_mrn(ex.document.patient_mrn)
    if mrn:
        mrn = corrected.get(_canon(mrn), mrn)
        if printed:
            if _canon(mrn) != _canon(printed[0]):
                return (*_mismatch(f"extracted MRN {mrn} differs from the MRN printed in the text ({printed[0]})",
                                   [printed[0], mrn]), None)
            return finish(printed[0])
        if _canon(mrn) not in {_canon(t) for t in _ID_TOKEN.findall(text.translate(_DASHES))}:
            return (*_mismatch(f"extracted MRN {mrn} does not appear in the document text", [mrn]), None)
        return finish(mrn)
    from_text = {"basis": "printed_mrn",
                 "reason": f"the text prints exactly one MRN ({printed[0]}); identity taken from the text, not the "
                           "extraction (which reported no MRN)"} if len(printed) == 1 else None
    name, dob = ex.document.patient_name, ex.document.patient_dob
    if not name:
        if from_text:
            return finish(printed[0], from_text)
        return None, {"status": "no_patient_identity", "candidates": [], "reason": "no MRN and no patient name"}, None
    hits = sorted(r["mrn"] for r in conn.execute(
        "SELECT mrn FROM patients WHERE name=? AND (dob=? OR ? IS NULL)", (name, dob, dob)))
    key = "name + DOB" if dob else "name (no DOB)"
    if len(hits) == 1:
        if printed:
            hit, pr = resolve_identifier(conn, hits[0])[0] or hits[0], resolve_identifier(conn, printed[0])[0] or printed[0]
            if _canon(hit) != _canon(pr):
                return (*_mismatch(f"no extracted MRN; {key} matches {hits[0]}, but the text prints MRN {printed[0]}",
                                   [hits[0], printed[0]]), None)
        return finish(hits[0])
    if hits:
        return None, {"status": "ambiguous_patient", "candidates": hits,
                      "reason": f"no MRN; {key} matches {len(hits)} known patients"}, None
    if from_text:
        # Conservative: the printed MRN must not belong to a known patient recorded under another name.
        known = conn.execute("SELECT name FROM patients WHERE mrn=?", (printed[0],)).fetchone()
        if known and known["name"] and known["name"] != name:
            return (*_mismatch(f"no extracted MRN; the text prints MRN {printed[0]}, a known patient named "
                               f"{known['name']!r}, but the extracted name is {name!r}", [printed[0]]), None)
        return finish(printed[0], from_text)
    return None, {"status": "no_patient_identity", "candidates": [],
                  "reason": f"no MRN; {key} matches no known patient"}, None


def attribute(conn: sqlite3.Connection, text: str, ex: Extraction) -> tuple[str | None, dict | None]:
    """`attribute_document` without the note: (mrn, None) or (None, quarantine record)."""
    return attribute_document(conn, text, ex)[:2]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def discover(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*") if x.is_file() and x.suffix.lower() in {".txt", ".md"}))
        elif p.is_file():
            out.append(p)
    return out


def _value_kind(v) -> str | None:
    """How to ground a free-text relation value: by the clock times or the date it contains, else not at all."""
    if not isinstance(v, str):
        return None
    if times_in(v):
        return "time"
    return "date" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v.strip()) else None


def grounding_fields(kind: str, p: dict) -> list[tuple[str, str, object, list[str]]]:
    """The payload values of one claim that must be stated in its own quotes (#36): clock times, stated minutes,
    scores and thresholds, and dates. A nontherapeutic interval may be grounded by its own quote or the event's."""
    if kind == "service_event":
        q = list(p.get("quotes") or [])
        out = [("service_date", "date", p.get("service_date"), q),
               ("patient_arrival", "time", p.get("patient_arrival"), q),
               ("patient_departure", "time", p.get("patient_departure"), q),
               ("stated_minutes", "minutes", p.get("stated_minutes"), q)]
        if p.get("scheduled"):
            out += [(f"scheduled.{k}", "time", p["scheduled"].get(k), q) for k in ("start", "end")]
        for i, iv in enumerate(p.get("patient_contact_intervals") or []):
            out += [(f"patient_contact_intervals[{i}].{k}", "time", iv.get(k), q) for k in ("start", "end")]
        for i, iv in enumerate(p.get("nontherapeutic_intervals") or []):
            out += [(f"nontherapeutic_intervals[{i}].{k}", "time", iv.get(k), [iv.get("quote")] + q)
                    for k in ("start", "end")]
        return out
    q = [p.get("quote")]
    if kind == "assessment":
        return [("total_score", "number", p.get("total_score"), q), ("completed_date", "date", p.get("completed_date"), q),
                ("completed_time", "time", p.get("completed_time"), q)]
    if kind == "observation":
        return [("date", "date", p.get("date"), q)]
    if kind == "plan_requirement":
        return [("threshold", "number", p.get("threshold"), q), ("effective_start", "date", p.get("effective_start"), q),
                ("effective_end", "date", p.get("effective_end"), q)]
    if kind == "relation":
        return [("original_date", "date", p.get("original_date"), q)] + [
            (k, _value_kind(p.get(k)), p.get(k), q) for k in ("old_value", "new_value") if _value_kind(p.get(k))]
    return []


def build_claims(sha: str, label: str, text: str, ex: Extraction, mrn: str | None) -> list[dict]:
    """Flatten one extraction into claims, verifying every quote against the document text."""
    idx = DocumentIndex(text)
    claims: list[dict] = []

    def add(kind: str, i: int, subject: str | None, payload: dict, quotes: list[str], evidence_type: str | None = None,
            supporting: list[str] = ()):
        # Every clinical claim needs at least one non-blank quote of its own, and every quote must be located.
        # Blank quotes are kept as "missing" spans (not dropped), so they fail verification and R0 rejects the
        # claim. `supporting` quotes (e.g. a break inside a session) are verified too but cannot stand in for the
        # claim's own evidence. The document claim carries no quotes and is not subject to R0.
        own = [idx.locate(q).as_dict() for q in quotes]
        spans = own + [idx.locate(q).as_dict() for q in supporting]
        grounded = kind == "document" or any((q or "").strip() for q in quotes)
        verified = int(grounded and all(s["match"] != "missing" for s in spans))
        if kind != "document":
            # Value grounding (#36), recorded as a flag, not a verification failure: per payload value, "quote" (stated
            # in the claim's own quotes), "document" (stated elsewhere in the text, e.g. a header date) or "absent".
            # It is the last evidence entry, with no line span, so it is never cited as a passage.
            fields = grounding_fields(kind, payload)
            in_quote, in_doc = ground_values(fields), ground_values([(f, k, v, [text]) for f, k, v, _ in fields])
            spans = spans + [{"quote": None, "line_start": None, "line_end": None, "match": "grounding",
                              "grounding": {f: "quote" if ok else "document" if in_doc[f] else "absent"
                                            for f, ok in in_quote.items()}}]
            # The values that set a session's minutes (clock times, stated minutes) must be stated in the claim's own
            # quotes: a verified quote must not carry an altered time into the arithmetic (#15, #36). Other values
            # (e.g. a date from the document header) stay a flag. On the supplied corpus this rejects no claim.
            kinds = {f: k for f, k, _, _ in fields}
            if kind == "service_event" and any(not ok for f, ok in in_quote.items() if kinds[f] in ("time", "minutes")):
                verified = 0
            # A date stated nowhere in the document was inferred, not extracted (the contract is to record what the
            # document states). Such a claim must not become dated evidence, and the schema has no undated form for
            # it (observations.obs_date is required), so it is unverified and R0 drops it (#52). The fields are
            # named on the grounding entry. On the supplied corpus this rejects one claim (a BH-D015 observation).
            absent_dates = sorted(f for f, ok in in_doc.items() if kinds[f] == "date" and not ok)
            if absent_dates:
                verified = 0
                spans[-1]["unverified_absent"] = absent_dates
        claims.append({
            "claim_id": f"{sha[:12]}:{kind}:{i}", "sha256": sha, "doc_label": label, "patient_mrn": mrn,
            "kind": kind, "subject_key": subject, "evidence_type": evidence_type,
            "payload": json.dumps(payload, sort_keys=True), "evidence": json.dumps(spans), "verified": verified,
        })

    doc = ex.document.model_dump()
    rels = doc.pop("relations")
    add("document", 0, label, doc, [])
    for i, r in enumerate(rels):
        add("relation", i, r.get("encounter_id") or r.get("form_id"), r, [r["quote"]])
    for i, ev in enumerate(ex.service_events):
        d = ev.model_dump()
        add("service_event", i, ev.encounter_id, d, list(ev.quotes), ev.evidence_type,
            supporting=[n.quote for n in ev.nontherapeutic_intervals])
    for i, a in enumerate(ex.assessments):
        add("assessment", i, a.form_id or f"{a.instrument}@{a.completed_date}", a.model_dump(), [a.quote])
    for i, o in enumerate(ex.observations):
        add("observation", i, o.date, o.model_dump(), [o.quote])
    for i, p in enumerate(ex.plan_requirements):
        add("plan_requirement", i, label, p.model_dump(), [p.quote])
    return claims


# --------------------------------------------------------------------------------------------- pending reconciles (#3)

def pending_patients(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT mrn FROM pending_reconcile ORDER BY mrn")]


def _mark_pending(conn: sqlite3.Connection, mrns) -> None:
    """Record, inside the caller's transaction, that these patients' evidence changed and they need reconciling."""
    conn.executemany("INSERT OR IGNORE INTO pending_reconcile VALUES (?,?)", [(m, _now()) for m in sorted(m for m in mrns if m)])


def clear_pending(conn: sqlite3.Connection, mrns) -> None:
    """Drop markers after a successful reconcile. Triggers already do this when a patients row is stamped or deleted;
    this covers a marker whose patient row no longer exists."""
    with conn:
        conn.executemany("DELETE FROM pending_reconcile WHERE mrn=?", [(m,) for m in sorted(set(mrns))])


# --------------------------------------------------------------------------------------------- attribution storage

def _store_attribution(conn: sqlite3.Connection, sha: str, label: str, text: str, ex: Extraction, mrn: str | None,
                       quarantine: dict | None, note: dict | None = None) -> None:
    """Point a document and all its claims at `mrn` (or quarantine them), record why when the basis was not the
    extracted MRN (`note`), and record any MRN correction its text states. Used by first ingest and by
    re-attribution, so both apply the same guards. A correction stated in a multi-patient document is not recorded:
    it cannot be tied to one patient, so it must not move other documents (#53). That status depends on the text
    alone, so the set of recorded corrections is a function of the documents' texts, never of attribution order."""
    conn.execute("UPDATE documents SET patient_mrn=? WHERE sha256=?", (mrn, sha))
    conn.execute("UPDATE claims SET patient_mrn=? WHERE sha256=?", (mrn, sha))
    conn.execute("DELETE FROM quarantine WHERE sha256=?", (sha,))
    if quarantine:
        conn.execute("INSERT INTO quarantine VALUES (?,?,?,?,?,?)",
                     (sha, label, quarantine["status"], quarantine["reason"], json.dumps(quarantine["candidates"]),
                      _now()))
    conn.execute("DELETE FROM attribution_notes WHERE sha256=?", (sha,))
    if mrn and note:
        conn.execute("INSERT INTO attribution_notes VALUES (?,?,?,?)", (sha, mrn, note["basis"], note["reason"]))
    conn.execute("DELETE FROM identifier_changes WHERE sha256=?", (sha,))
    if not (quarantine and quarantine["status"] == "multi_patient"):
        conn.executemany("INSERT OR IGNORE INTO identifier_changes VALUES (?,?,?,?,?)",
                         [(sha, *c) for c in text_identity(text).corrections])
    if mrn and not conn.execute("SELECT 1 FROM patients WHERE mrn=?", (mrn,)).fetchone():
        conn.execute("INSERT INTO patients(mrn, name, dob) VALUES (?,?,?)",
                     (mrn, ex.document.patient_name, ex.document.patient_dob))


def reattribute(conn: sqlite3.Connection, *, skip: set[str] = frozenset(), log=print) -> list[dict]:
    """Re-run attribution (#41) using each document's stored extraction (never the LLM) for: every quarantined
    document; every document attributed by name alone (a later same-name patient makes the match ambiguous); and
    every document an MRN correction may move (#53): one owned by, or attributed via, an MRN that a recorded correction
    replaces, or attributed through a correction earlier. `skip` (this run's freshly attributed documents) applies to
    the first two only, since a correction stated later in the same batch must still move them.

    Repeated to a fixed point: a printed-MRN attribution (#55) can create a patient that a name-only document then
    matches. The recorded corrections depend only on documents' texts and patients are only ever added here, so this
    converges; the bound is a safeguard. Only actual changes are applied, marked pending and reported."""
    changes: list[dict] = []
    n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    for _ in range(n_docs + 1):
        moved = _reattribute_pass(conn, skip, log)
        changes += moved
        if not moved:
            break
    return changes


def _reattribute_pass(conn: sqlite3.Connection, skip, log) -> list[dict]:
    shas = {r[0] for r in conn.execute("SELECT sha256 FROM quarantine")}
    shas |= {r[0] for r in conn.execute("SELECT sha256 FROM claims WHERE kind='document' "
                                        "AND json_extract(payload, '$.patient_mrn') IS NULL")}
    shas -= set(skip)
    old = {_canon(r[0]) for r in conn.execute("SELECT old_mrn FROM identifier_changes")}
    if old:
        for r in conn.execute("SELECT d.sha256, d.patient_mrn, json_extract(c.payload, '$.patient_mrn') FROM documents d "
                              "JOIN claims c ON c.sha256 = d.sha256 AND c.kind = 'document'"):
            if any(m and _canon(m) in old for m in (r[1], r[2])):
                shas.add(r[0])
    shas |= {r[0] for r in conn.execute("SELECT sha256 FROM attribution_notes WHERE basis='identifier_change'")}
    changes = []
    for sha in sorted(shas):
        raw = conn.execute("SELECT raw_json FROM extractions WHERE sha256=? ORDER BY rowid DESC LIMIT 1",
                           (sha,)).fetchone()
        if not raw:
            continue
        doc = conn.execute("SELECT doc_label, text, patient_mrn, paths FROM documents WHERE sha256=?", (sha,)).fetchone()
        old_q = conn.execute("SELECT status, candidates FROM quarantine WHERE sha256=?", (sha,)).fetchone()
        old_n = conn.execute("SELECT basis, reason FROM attribution_notes WHERE sha256=?", (sha,)).fetchone()
        ex = Extraction.model_validate_json(raw[0])
        mrn, quarantine, note = attribute_document(conn, doc["text"], ex)
        before = (doc["patient_mrn"], old_q and old_q["status"], old_q and json.loads(old_q["candidates"]),
                  old_n and dict(old_n))
        if before == (mrn, quarantine and quarantine["status"], quarantine and quarantine["candidates"], note):
            continue
        _store_attribution(conn, sha, doc["doc_label"], doc["text"], ex, mrn, quarantine, note)
        if mrn != doc["patient_mrn"]:
            _mark_pending(conn, {doc["patient_mrn"], mrn})
            reason = quarantine["reason"] if quarantine else note["reason"] if note else None
            changes.append({"file": json.loads(doc["paths"])[0], "doc_label": doc["doc_label"],
                            "from": doc["patient_mrn"], "to": mrn,
                            **({"status": quarantine["status"]} if quarantine else {}),
                            **({"basis": note["basis"]} if note else {}),
                            **({"reason": reason} if reason else {})})
            log(f"  RE-ATTRIBUTED {doc['doc_label']}: {doc['patient_mrn'] or 'quarantine'} -> {mrn or 'quarantine'}")
    return changes


def ingest(conn: sqlite3.Connection, paths: list[str | Path], *, model: str = DEFAULT_MODEL,
           effort: str = "high", workers: int | None = None, log=print) -> dict:
    """Ingest files. Idempotent: byte-identical files are recorded once; cached extractions are reused."""
    t0 = time.monotonic()
    files = discover(paths)
    workers = workers or int(os.environ.get("BACKBONE_CONCURRENCY", "6"))
    todo: dict[str, tuple[Path, str]] = {}
    stats = {"files": len(files), "new_documents": 0, "duplicate_files": 0, "extracted_llm": 0,
             "extracted_cache": 0, "already_ingested": 0, "failed": [], "affected_patients": [], "quarantined": [],
             "reattributed": [], "attribution_notes": [], "pending_from_earlier_runs": pending_patients(conn),
             "llm_cost_usd": 0.0, "llm_input_tokens": 0, "llm_output_tokens": 0, "llm_latency_ms": []}

    for f in files:
        raw = f.read_bytes()
        sha = sha256_bytes(raw)
        text = raw.decode("utf-8", errors="replace")
        row = conn.execute("SELECT paths FROM documents WHERE sha256=?", (sha,)).fetchone()
        if row:
            known = json.loads(row["paths"])
            if str(f) not in known:
                known.append(str(f))
                conn.execute("UPDATE documents SET paths=? WHERE sha256=?", (json.dumps(known), sha))
                stats["duplicate_files"] += 1
            have = conn.execute("SELECT 1 FROM extractions WHERE sha256=? AND extractor_version=? AND model=?",
                                (sha, EXTRACTOR_VERSION, model)).fetchone()
            if have:
                stats["already_ingested"] += 1
                continue
        elif sha in todo:
            stats["duplicate_files"] += 1
            continue
        else:
            m = HEADER_ID.search(text)
            label = m.group(1) if m else f.stem
            conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) "
                         "VALUES (?,?,?,?,?,?)", (sha, label, json.dumps([str(f)]), text, None, _now()))
            stats["new_documents"] += 1
        todo[sha] = (f, text)
    conn.commit()

    def work(sha: str):
        f, text = todo[sha]
        return sha, *extract_document(sha, f.name, text, model=model, effort=effort)

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(work, sha): sha for sha in todo}
        for fut in as_completed(futs):
            sha = futs[fut]
            try:
                results.append(fut.result())
                _, _, meta = results[-1]
                src = "cache" if meta.get("from_cache") else f"LLM {(meta.get('latency_ms') or 0)/1000:.1f}s"
                log(f"  extracted {todo[sha][0].name} ({src})")
            except Exception as e:  # one bad document must not sink the run
                stats["failed"].append({"file": str(todo[sha][0]), "error": str(e)[:300]})
                log(f"  FAILED {todo[sha][0].name}: {str(e)[:200]}")

    # Documents carrying an MRN first, so a name-only document in the same batch can match a patient they create.
    for sha, ex, meta in sorted(results, key=lambda r: (norm_mrn(r[1].document.patient_mrn) is None, r[0])):
        label = conn.execute("SELECT doc_label FROM documents WHERE sha256=?", (sha,)).fetchone()["doc_label"]
        text = todo[sha][1]
        # Former owners of this document's evidence (re-extraction may move or quarantine it): they must be
        # re-reconciled too, or they keep derived rows built from claims that no longer belong to them.
        former = {r[0] for r in conn.execute(
            "SELECT DISTINCT patient_mrn FROM claims WHERE sha256=? AND patient_mrn IS NOT NULL", (sha,))}
        former |= {r[0] for r in conn.execute(
            "SELECT patient_mrn FROM documents WHERE sha256=? AND patient_mrn IS NOT NULL", (sha,))}
        mrn, quarantine, note = attribute_document(conn, text, ex)
        conn.execute("DELETE FROM claims WHERE sha256=?", (sha,))
        for c in build_claims(sha, label, text, ex, mrn):
            conn.execute("INSERT INTO claims VALUES (:claim_id,:sha256,:doc_label,:patient_mrn,:kind,:subject_key,"
                         ":evidence_type,:payload,:evidence,:verified)", c)
        conn.execute("INSERT OR REPLACE INTO extractions VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (sha, EXTRACTOR_VERSION, model, json.dumps(ex.model_dump()), meta.get("latency_ms"),
                      meta.get("input_tokens"), meta.get("output_tokens"), meta.get("cost_usd"),
                      int(bool(meta.get("from_cache"))), _now()))
        _store_attribution(conn, sha, label, text, ex, mrn, quarantine, note)
        if note:
            stats["attribution_notes"].append({"file": str(todo[sha][0]), "doc_label": label, "mrn": mrn, **note})
        _mark_pending(conn, former | {mrn})
        if quarantine:
            stats["quarantined"].append({"file": str(todo[sha][0]), "doc_label": label, **quarantine})
            log(f"  QUARANTINED {todo[sha][0].name}: {quarantine['reason']}")
        if meta.get("from_cache"):
            stats["extracted_cache"] += 1
        else:
            stats["extracted_llm"] += 1
            stats["llm_cost_usd"] += meta.get("cost_usd") or 0.0
            stats["llm_input_tokens"] += meta.get("input_tokens") or 0
            stats["llm_output_tokens"] += meta.get("output_tokens") or 0
            stats["llm_latency_ms"].append(meta.get("latency_ms") or 0)
    stats["reattributed"] = reattribute(conn, skip={r[0] for r in results}, log=log)
    conn.commit()        # claims, attribution and pending markers commit together (#3)
    # Everyone owed a reconcile: this run's changes plus anything a crashed earlier run left pending.
    stats["affected_patients"] = pending_patients(conn)
    stats["quarantined"].sort(key=lambda q: q["file"])
    stats["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return stats
