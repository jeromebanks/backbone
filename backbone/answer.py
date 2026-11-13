"""Question answering: question -> QueryPlan (LLM) -> deterministic execution -> cited narrative (LLM) -> post-check.

The LLM only (1) chooses operations and parameters and (2) explains computed results. Numbers come from the
operators; the post-check flags any number or citation in the narrative that is not present in the results.
Answers are cached by (question, abstraction fingerprint, prompt version), so repeated questions cost nothing. A
narration that fails the post-check is regenerated once with the failures fed back; if it still fails, the answer is
returned flagged and is not cached.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

from . import EXTRACTOR_VERSION, QUERY_VERSION, RULESET_VERSION
from .db import ROOT, connect, connect_readonly
from .llm import complete_json
from .paths import safe_output_path
from .query import QueryPlan, execute_plan

PROMPT_VERSION = "a2"
OUT_DIR = ROOT / "out" / "answers"

PLANNER_SYSTEM = """You translate a question about clinical records into a QueryPlan: a list of typed operations that \
software executes deterministically over a reconciled clinical abstraction. You do not answer the question and you \
never do arithmetic; you only choose operations and parameters. The JSON schema is enforced.

Operations (every step has a scope: patients = list of MRNs or "all", start/end dates, optional service_types, \
include_excluded, include_evidence):
- care(group_by: none|service_type|day|week|patient): therapy sessions that count, distinct therapy days, \
patient-present minutes and hours, each as [low, high] bounds, broken down by service type; with include_excluded=true \
it also lists every encounter that does NOT count and why, and the reconciliation decisions about duplicate, \
corrected, draft, billing or copied records.
- compliance(consecutive_below: N|null): for each Monday–Sunday week, the treatment-plan goal in effect, the delivered \
therapy days/minutes, and MET / NOT_MET / UNDETERMINED with reasons; consecutive_below=N finds runs of N+ weeks below \
goal (and whether a patient's inclusion depends on unresolved documentation).
- timeline(kinds ⊆ [encounters, documents, decisions, assessments, observations], observation_domains): chronological \
facts. Use a one-day scope (start = end) with kinds [encounters, documents, decisions] to reconstruct what happened on \
a date and how each record (attendance, notes, corrections, copies, telehealth logs) affects it. Use assessments + \
observations for symptom course and progress questions.
- compare(split: a date or "plan_change"): care before vs after a date or a treatment-plan change.

Guidance
- Use one step per distinct need; several steps are fine. Use the exact dates in the question. If the question \
refers to "the review period" or "the episode" without dates, use the patient's episode dates from the directory.
- Set include_excluded=true whenever the question asks about duplicates, ineligible or excluded records, or asks you to \
explain how records affect the answer. Keep include_evidence=true.
- When a symptom/progress question also asks why a particular contact happened, add a timeline step for that date \
with kinds [encounters, documents, decisions].
- Resolve patient names to MRNs using the directory. Use patients="all" for collection-wide questions.
- If the question cannot be answered with these operations, return no steps and explain in unsupported_reason."""

NARRATOR_SYSTEM = """You write the final answer to a question about clinical records, using ONLY the computed results \
provided (produced by deterministic software from source documents). Rules:
- Every number you state must appear in the results. Do not compute new numbers (no new sums, differences, averages \
or conversions); quote the computed values, including [low–high] bounds.
- Cite sources inline as (DOC-ID L<lines>) using the evidence entries, e.g. (BH-D103 L7). Cite only documents that \
appear in the results, and only line numbers listed in that document's evidence passages (their "lines" field). A \
range is allowed only when every line in it is listed: never join non-adjacent lines into a range. If the listed lines \
are 6, 7 and 9, write (BH-D103 L6–7, L9), not (BH-D103 L6–9). Prefix every line number with L.
- Lead with the direct answer, then supporting detail (a compact markdown table is good for per-week or per-type \
numbers), then what the record does not settle (bounds, disputes, UNDETERMINED weeks, missing documentation), and \
the records that were excluded or merged and why (duplicates, corrections, drafts, billing, copies, collateral or \
non-therapy contacts) when relevant to the question.
- Separate documented facts from interpretation. Do not claim improvement, causation or outcomes that the cited \
observations and assessments do not state.
- Be concise and specific: write for a clinical reviewer who will check your citations."""


class NarrativeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_markdown: str
    unresolved: list[str]
    caveats: Optional[list[str]]


def directory(conn) -> str:
    rows = conn.execute("""
        SELECT p.mrn, p.name, p.dob,
               (SELECT MIN(service_date) FROM encounters e WHERE e.mrn=p.mrn) AS first_enc,
               (SELECT MAX(service_date) FROM encounters e WHERE e.mrn=p.mrn) AS last_enc,
               (SELECT COUNT(*) FROM documents d WHERE d.patient_mrn=p.mrn) AS docs,
               (SELECT GROUP_CONCAT(DISTINCT doc_label || ' ' || COALESCE(effective_start,'?') || '..' || COALESCE(effective_end,'?'))
                  FROM plan_requirements r WHERE r.mrn=p.mrn) AS plans
        FROM patients p ORDER BY p.mrn""").fetchall()
    return "\n".join(f"- MRN {r['mrn']}: {r['name']} (DOB {r['dob']}); {r['docs']} documents; encounters "
                     f"{r['first_enc']}..{r['last_enc']}; treatment plans (effective): {r['plans'] or 'none'}"
                     for r in rows)


# What an answer is computed from: the evidence layer (documents, which extractions were committed, claims) and the
# derived clinical layer. Each table is hashed minus the columns that change when identical content is rebuilt
# (rowids, timestamps, LLM timing/cost) or that another hashed column identifies (document text by its sha256; the
# raw extraction JSON by the claims built from it). Every other column is hashed, including columns added later.
_FP_TABLES = {
    "documents": {"text", "ingested_at"},
    "extractions": {"raw_json", "latency_ms", "input_tokens", "output_tokens", "cost_usd", "from_cache", "created_at"},
    "claims": set(),
    "patients": {"reconciled_at"},
    "encounters": set(),
    "encounter_intervals": set(),
    "plan_requirements": set(),
    "assessments": set(),
    "observations": set(),
    "decisions": {"decision_id"},
    "conflicts": {"conflict_id"},
}


def fingerprint(conn) -> str:
    """Content hash of the abstraction that answers are computed from, plus the code versions. It changes when an
    extraction is committed (e.g. a failed one is retried, or a document is re-extracted with another model), when
    claims change, or when reconciliation produces different derived rows. An identical rebuild leaves it unchanged.
    Rows are streamed into the hash in a content-defined order (the primary key where it is stable, else every hashed
    column): one scan per table, nothing materialised. About 2 ms on the supplied corpus."""
    h = hashlib.sha256(json.dumps([EXTRACTOR_VERSION, RULESET_VERSION, QUERY_VERSION, PROMPT_VERSION]).encode())
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, volatile in _FP_TABLES.items():
        if table not in tables:
            continue
        info = list(conn.execute(f"PRAGMA table_info({table})"))       # (cid, name, type, notnull, default, pk)
        cols = [f'"{r[1]}"' for r in info if r[1] not in volatile]
        pk = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5] > 0]
        order = [f'"{c}"' for c in pk] if pk and not set(pk) & volatile else cols
        h.update(f"\x1e{table}({','.join(cols)})".encode())
        for row in conn.execute(f"SELECT {','.join(cols)} FROM {table} ORDER BY {','.join(order)}"):
            h.update(repr(tuple(row)).encode() + b"\n")
    return h.hexdigest()


def _slim(results: dict) -> dict:
    """What the narrator sees: results without SQL text."""
    out = json.loads(json.dumps(results, default=str))
    for r in out.get("results", []):
        r.pop("sql", None)
    return out


_NUM = re.compile(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])")

# Calendar and clock notation: its digits name a date or a time, not a quantity. Stripped from the answer before its
# numbers are checked, and from computed strings before their numbers are admitted (#44), so the two sides agree.
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
           r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?(?![A-Za-z])")
_CALENDAR = [
    re.compile(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?(?!\d)"),      # ISO date / datetime
    re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])"),                             # clock time
    re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}/\d{2,4}(?![\d/])"),                               # 1/7/2026
    re.compile(rf"\b\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?\s+{_MONTHS}(?:\s+\d{{4}})?(?!\d)"),    # 26 January 2026
    # Jan 26–30, 2026 · Jan 8, 15 and 27 (a list of days; a number followed by a unit is not a day)
    re.compile(rf"\b{_MONTHS}\s*\d{{1,2}}(?!\d)(?:\s*[-–]\s*\d{{1,2}}(?!\d))?"
               rf"(?:(?:,\s*|,?\s+(?:and|&)\s+)\d{{1,2}}(?![\d.,])(?!\s*(?:min|hour|hr|h\b|session|day|week|wk|%)))*"
               rf"(?:,?\s*\d{{4}})?"),
    re.compile(rf"\b{_MONTHS}\s+\d{{4}}(?!\d)"),                                               # January 2026
]
# Identifiers inside computed strings: keys (MRN|ENC), claim ids, short shas and other hex, and labels or file names
# such as BH-D103, HG-M042, PHQ-9 or note_88.txt. Their digits are never quantities.
_IDENTIFIERS = [
    # A year-less "1/7" is a date in a source quote, but in an answer it may be a ratio ("4/5 sessions"), so it is
    # removed from computed strings only and stays checked in the answer.
    re.compile(r"(?<![\d/])\d{1,2}/\d{1,2}(?![\d/])"),
    re.compile(r"\S*\|\S*"),
    re.compile(r"\b[0-9a-f]{12}:[a-z_]+:\d+\b"),
    re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b"),
    re.compile(r"\[[0-9a-f]{12}\]"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)*[-_.][A-Za-z]?\d[\w.-]*"),
]
_QUANTITY = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)")
# Fields whose values identify something (claims, documents, files, keys, rules, line numbers) rather than state a
# quantity: nothing under them is admitted, whatever its type.
_ID_FIELDS = {"claim_id", "claim_ids", "file", "sha256", "doc_sha", "requirement", "doc_id", "lines", "line_start",
              "line_end", "mrn", "encounter_id", "form_id", "subject", "rule"}


def _strip_calendar(s: str) -> str:
    for rx in _CALENDAR:
        s = rx.sub(" ", s)
    return s


def _known_numbers(results: dict) -> set[float]:
    """The numbers the computed results state (#44): every JSON number, plus every free-standing number in a
    human-readable string (calculations, reasons, notes, statements, evidence quotes), outside identifier fields and
    after removing dates, clock times and identifiers. An unanchored digit scan over the whole envelope admitted the
    digits of claim-ID hex, keys, file names and dates, so an invented small number usually passed."""
    out: set[float] = set()

    def walk(o, key):
        if key in _ID_FIELDS or key.endswith(("_key", "_id", "_ids", "_sha")):
            return
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, str(k))
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, bool) or o is None:
            return
        elif isinstance(o, (int, float)):
            out.add(float(o))
        elif isinstance(o, str):
            s = _strip_calendar(o)
            for rx in _IDENTIFIERS:
                s = rx.sub(" ", s)
            out.update(float(t) for t in _QUANTITY.findall(s))

    walk(json.loads(_computed_blob(results)), "")
    return out


def _computed_blob(results: dict) -> str:
    """The results envelope minus everything that did not come from the abstraction: the question and plan echo
    whatever the asker typed, each step's `params` echo the plan's arguments (thresholds, dates, run lengths), and
    SQL text holds literals. Numbers and documents in the answer must be backed by what is left (totals, groups,
    facts, calculations, exclusions, decisions, evidence quotes, notes). A parameter value is admitted only where the
    operator also states it in that computed output."""
    out = json.loads(json.dumps(results, default=str))
    out.pop("question", None)
    out.pop("plan", None)
    for r in out.get("results", []):
        r.pop("sql", None)
        r.pop("params", None)
    return json.dumps(out)


def postcheck(conn, answer_md: str, results: dict) -> dict:
    blob = _computed_blob(results)
    known = _known_numbers(results)
    text = re.sub(r"\b[A-Z]{2,}-[A-Z]?\d+\b", " ", answer_md)          # drop IDs like BH-D103, HG-E110
    text = re.sub(r"\[[0-9a-f]{12}\]", " ", text)                       # short shas disambiguating a label (#59)
    text = re.sub(r"\bL\d+(?:[-–]\d+)?\b", " ", text)                    # drop line refs
    text = _strip_calendar(text)                                          # dates and clock times (checked via quotes)
    unknown = sorted({n for n in _NUM.findall(text) if float(n) not in known}, key=float)
    # Citations: the pattern is built from the corpus's own document labels (any ID scheme or filename stem).
    shas: dict[str, list[str]] = {}
    for lab, sha in conn.execute("SELECT doc_label, sha256 FROM documents ORDER BY sha256"):
        shas.setdefault(lab, []).append(sha)
    labels = sorted(shas, key=len, reverse=True)
    shared = {lab for lab, s in shas.items() if len(s) > 1}
    # A label several documents carry is not an identity (#40): results then name each one "LABEL [sha12]", and a
    # citation must do the same (#59). Group 1 is the label, group 2 the optional short sha.
    label_re = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, labels)) + r")(?![\w-])(?:\s*\[([0-9a-f]{12})\])?"
                          ) if labels else None

    def ref(lab: str, sha: str | None) -> str:
        return f"{lab} [{sha}]" if sha else lab

    matches = list(label_re.finditer(answer_md)) if label_re else []
    cited = {(m.group(1), m.group(2)) for m in matches}
    # What the results name: label mentions in the computed output, and each evidence entry's (doc_id, doc_sha).
    in_results = {(m.group(1), m.group(2)) for m in label_re.finditer(blob)} if label_re else set()
    for r in results.get("results", []):
        for ev in r.get("evidence", []):
            in_results.add((ev["doc_id"], ev.get("doc_sha")))
    result_labels = {lab for lab, _ in in_results}
    ambiguous = sorted({lab for lab, sha in cited if lab in shared and not sha})
    unknown_sha = sorted({ref(lab, sha) for lab, sha in cited
                          if sha and not any(s.startswith(sha) for s in shas.get(lab, []))})
    not_in_results = sorted({ref(lab, sha) for lab, sha in cited if ref(lab, sha) not in unknown_sha
                             and not ((lab, sha) in in_results if sha else lab in result_labels)})
    # Things that look like document citations "(XYZ-123 L4)" but name no document in the corpus.
    known_ids = set(labels) | set(re.findall(r"[A-Z]{1,}-[A-Z]?\d+", blob))
    bad_docs = sorted({m for m in re.findall(r"\(([A-Za-z][\w.-]*\d)\s+L\d+", answer_md) if m not in known_ids}
                      | set(unknown_sha))
    # Every line reference in a citation group must fall inside an evidence passage for that document. Spans are
    # keyed by (label, short sha): passages of two same-label documents never back each other's lines (#59).
    spans: dict[tuple[str, str | None], list[tuple[int, int]]] = {}
    for r in results.get("results", []):
        for ev in r.get("evidence", []):
            for p in ev["passages"]:
                a, _, b = p["lines"].partition("-")
                spans.setdefault((ev["doc_id"], ev.get("doc_sha")), []).append((int(a), int(b or a)))

    def spans_for(lab: str, sha: str | None) -> list[tuple[int, int]]:
        if lab in shared:            # only the cited document's own passages; an undisambiguated citation has none
            return spans.get((lab, sha), []) if sha else []
        return [s for (d, _), v in spans.items() if d == lab for s in v]

    bad_lines = []
    for i, m in enumerate(matches):
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(answer_md)
        seg = re.split(r"[);\]]", answer_md[m.end():seg_end], maxsplit=1)[0]
        doc = ref(m.group(1), m.group(2))
        for a, b in re.findall(r"L(\d+)(?:\s*[-–]\s*L?(\d+))?", seg):
            lo, hi = int(a), int(b or a)
            if lo > hi:
                bad_lines.append((doc, lo, f"L{lo}-{hi}"))
                continue
            # Every line of a cited range must be inside some evidence passage for that document (passages
            # may be adjacent; their union must cover the range). Documents with no passages in the results
            # cannot back any line reference.
            for ln in range(lo, hi + 1):
                if not any(x <= ln <= y for x, y in spans_for(m.group(1), m.group(2))):
                    bad_lines.append((doc, ln, f"L{ln}"))
    bad_lines = [f"{doc} {ref}" for doc, _, ref in sorted(set(bad_lines))]
    return {"numbers_not_in_results": unknown, "unknown_documents": bad_docs,
            "documents_not_in_results": not_in_results, "line_refs_outside_evidence": bad_lines,
            "ambiguous_citations": ambiguous,
            "ok": not (unknown or bad_docs or not_in_results or bad_lines or ambiguous)}


def _narration_prompt(question: str, results: dict) -> str:
    return f"Question:\n{question}\n\nComputed results (JSON):\n{json.dumps(_slim(results), indent=1, default=str)}"


def _retry_feedback(answer_md: str, pc: dict) -> str:
    failures = {k: v for k, v in pc.items() if k != "ok" and v}
    return ("\n\nYour previous answer (below) failed the automatic post-check. Rewrite it so that it passes: state "
            "only numbers that appear in the computed results, cite only documents that appear in them, and cite only "
            "line numbers listed in that document's evidence passages (list non-adjacent lines separately, never as "
            "one range).\n\nPost-check failures (JSON):\n" + json.dumps(failures, indent=1)
            + "\n\nPrevious answer:\n" + answer_md)


def answer_question(question: str, *, db_path=None, use_cache: bool = True, qid: str | None = None) -> dict:
    conn = connect(db_path)
    fp = fingerprint(conn)
    key = hashlib.sha256((question + fp).encode()).hexdigest()
    if use_cache:
        t0 = time.monotonic()
        row = conn.execute("SELECT result_json FROM answer_cache WHERE cache_key=?", (key,)).fetchone()
        res = json.loads(row["result_json"]) if row else None
        # An answer that fails its post-check is never served. The check is re-run, not read from the row: a row
        # written under an older, looser post-check (#44, #59) must not be served on the strength of its stored "ok".
        if res and "results" in res:
            res["postcheck"] = postcheck(conn, res["answer_markdown"], res["results"])
        if res and (res.get("postcheck") or {}).get("ok"):
            res["cached"] = True
            res["timings_ms_original"] = res["timings_ms"]
            res["timings_ms"] = {"cache_lookup": round((time.monotonic() - t0) * 1000, 2)}
            return res
    llm = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def acc(r):
        llm["calls"] += 1
        llm["input_tokens"] += r.input_tokens
        llm["output_tokens"] += r.output_tokens
        llm["cost_usd"] += r.cost_usd or 0.0

    t0 = time.monotonic()
    plan_prompt = f"Patient directory:\n{directory(conn)}\n\nQuestion:\n{question}"
    pr = complete_json(PLANNER_SYSTEM, plan_prompt, QueryPlan, effort="medium")
    acc(pr)
    plan: QueryPlan = pr.data
    plan.question = question
    t1 = time.monotonic()
    results = execute_plan(conn, plan)
    t2 = time.monotonic()
    first_failure = None
    if not plan.steps:      # no narrator to regenerate: the planner's reason is post-checked as it stands
        answer = {"answer_markdown": f"**Not answerable with the supported operations.** {plan.unsupported_reason}",
                  "unresolved": [], "caveats": None}
        pc, attempts = postcheck(conn, answer["answer_markdown"], results), 1
    else:
        prompt = _narration_prompt(question, results)
        nr = complete_json(NARRATOR_SYSTEM, prompt, NarrativeOut, effort="medium")
        acc(nr)
        answer = nr.data.model_dump()
        pc, attempts = postcheck(conn, answer["answer_markdown"], results), 1
        if not pc["ok"]:    # the post-check is a gate: regenerate once, same results, with the failures fed back
            first_failure = pc
            nr = complete_json(NARRATOR_SYSTEM, prompt + _retry_feedback(answer["answer_markdown"], pc),
                               NarrativeOut, effort="medium")
            acc(nr)
            answer = nr.data.model_dump()
            pc, attempts = postcheck(conn, answer["answer_markdown"], results), 2
    t3 = time.monotonic()
    res = {
        "id": qid, "question": question, "plan": plan.model_dump(mode="json"), "plan_explain": plan.explain(),
        "results": results, "answer_markdown": answer["answer_markdown"], "unresolved": answer["unresolved"],
        "caveats": answer.get("caveats"), "postcheck": pc, "postcheck_attempts": attempts,
        "postcheck_first_attempt": first_failure,
        "timings_ms": {"plan_llm": int((t1 - t0) * 1000), "execute": round((t2 - t1) * 1000, 2),
                       "narrate_llm": int((t3 - t2) * 1000), "total": int((t3 - t0) * 1000)},
        "llm": llm, "cached": False, "fingerprint": fp,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if pc["ok"]:            # a failing answer is returned (flagged by its post-check) but never cached as good
        conn.execute("INSERT OR REPLACE INTO answer_cache VALUES (?,?,?,?)",
                     (key, question, json.dumps(res, default=str), res["created_at"]))
        conn.commit()
    return res


POSTCHECK_FAILED_BANNER = ("> **Post-check failed:** this answer states numbers or citations that the computed results "
                           "do not back. Read the post-check section before relying on it.")


def render_markdown(res: dict) -> str:
    lines = [f"# {res.get('id') or 'Answer'}", "", f"> {res['question']}", ""]
    if not res["postcheck"].get("ok", True):
        lines += [POSTCHECK_FAILED_BANNER, ""]
    lines += [res["answer_markdown"], ""]
    if res.get("unresolved"):
        lines += ["## Not settled by the record", ""] + [f"- {u}" for u in res["unresolved"]] + [""]
    lines += ["## How this was computed", "", "```", res["plan_explain"], "```", ""]
    for r in res["results"].get("results", []):
        if r.get("calculation"):
            lines += [f"**{r['op']}**", ""] + [f"- {c}" for c in r["calculation"]] + [""]
    pc = res["postcheck"]
    lines += ["## Post-check", "", f"- numbers in the answer not found in computed results: {pc['numbers_not_in_results'] or 'none'}",
              f"- cited documents not in the corpus: {pc['unknown_documents'] or 'none'}",
              f"- cited documents not in the computed results: {pc.get('documents_not_in_results') or 'none'}",
              f"- line references outside the evidence passages: {pc['line_refs_outside_evidence'] or 'none'}"]
    if pc.get("ambiguous_citations"):     # only printed when present, so existing saved Markdown is unchanged
        lines.append(f"- cited labels shared by several documents, without [sha]: {pc['ambiguous_citations']}")
    lines += [""]
    ev = {}
    for r in res["results"].get("results", []):
        for e in r.get("evidence", []):
            for p in e["passages"]:
                ev[(e["doc_id"], p["lines"])] = (e["file"], e["record_type"], p["quote"])
    if ev:
        lines += ["## Evidence passages", "", "| Doc | Lines | File | Record | Quote |", "|---|---|---|---|---|"]
        for (doc, ln), (f, rt, q) in sorted(ev.items(), key=lambda kv: (kv[0][0], int(kv[0][1].split('-')[0]))):
            lines.append(f"| {doc} | {ln} | {f} | {rt} | {q.replace('|', '/')} |")
    t, l = res.get("timings_ms_original") or res["timings_ms"], res.get("llm", {})
    lines += ["", f"_timings (ms): {t}; LLM calls: {l.get('calls')}, tokens in/out: {l.get('input_tokens')}/"
                  f"{l.get('output_tokens')}, list-price cost ${l.get('cost_usd', 0):.3f}; cached: {res.get('cached')}_"]
    return "\n".join(lines)


def verify_answers(*, db_path=None, rewrite: bool = False) -> list[dict]:
    """Re-execute every saved answer's QueryPlan against the current abstraction (no LLM) and confirm the results are
    identical to those the narrative was written from; re-run the post-check. Reproducibility check for reviewers.

    Read-only by default: the database is opened read-only and no file is written. rewrite=True refreshes each saved
    answer's post-check field and its Markdown; the results and the narrative are never changed."""
    ro = connect_readonly(db_path)
    report = []
    for p in sorted(OUT_DIR.glob("*.json")):
        res = json.loads(p.read_text())
        if "plan" not in res:
            continue
        plan = QueryPlan.model_validate(res["plan"])
        fresh = json.loads(json.dumps(execute_plan(ro, plan), default=str))
        same = json.dumps(fresh, sort_keys=True) == json.dumps(res["results"], sort_keys=True, default=str)
        pc = postcheck(ro, res["answer_markdown"], res["results"])
        report.append({"id": res.get("id"), "results_identical": same, "postcheck_ok": pc["ok"], "postcheck": pc})
        if rewrite:
            res["postcheck"] = pc
            p.write_text(json.dumps(res, indent=2, default=str))
            p.with_suffix(".md").write_text(render_markdown(res))
    return report


def answer_file(path: str, *, db_path=None, use_cache: bool = True) -> list[dict]:
    qs = json.loads(Path(path).read_text())
    # Every question ID becomes a file name: validate them all before the first (paid) LLM call.
    ids = [q.get("id") for q in qs]
    targets = [(safe_output_path(OUT_DIR, i, ".json"), safe_output_path(OUT_DIR, i, ".md")) for i in ids]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate question ids would overwrite each other's answers: {dupes}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for q, (pj, pm) in zip(qs, targets):
        res = answer_question(q["question"], db_path=db_path, use_cache=use_cache, qid=q["id"])
        res["id"] = q["id"]
        pj.write_text(json.dumps(res, indent=2, default=str))
        pm.write_text(render_markdown(res))
        print(f"{q['id']}: total {res['timings_ms']} cached={res['cached']} postcheck_ok={res['postcheck']['ok']}")
        out.append(res)
    combined = [f"# Answers: {Path(path).name}", ""]
    for r in out:
        flag = [POSTCHECK_FAILED_BANNER, ""] if not r["postcheck"]["ok"] else []
        combined += [f"## {r['id']}", "", f"> {r['question']}", "", *flag, r["answer_markdown"], "",
                     f"_Details, plan, calculations and evidence: [{r['id']}.md]({r['id']}.md)_", ""]
    name = "ANSWERS.md" if Path(path).name == "questions.json" else f"ANSWERS_{Path(path).stem}.md"
    (OUT_DIR / name).write_text("\n".join(combined))
    return out
