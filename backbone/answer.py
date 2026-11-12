"""Question answering: question -> QueryPlan (LLM) -> deterministic execution -> cited narrative (LLM) -> post-check.

The LLM only (1) chooses operations and parameters and (2) explains computed results. Numbers come from the
operators; the post-check flags any number or citation in the narrative that is not present in the results.
Answers are cached by (question, abstraction fingerprint, prompt version), so repeated questions cost nothing.
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
from .db import ROOT, connect
from .llm import complete_json
from .query import QueryPlan, execute_plan

PROMPT_VERSION = "a1"
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
- Cite sources inline as (DOC-ID L<lines>) using the evidence entries, e.g. (BH-D103 L7). Cite only documents and \
lines that appear in the results.
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


def fingerprint(conn) -> str:
    shas = [r[0] for r in conn.execute("SELECT sha256 FROM documents ORDER BY sha256")]
    return hashlib.sha256(json.dumps([EXTRACTOR_VERSION, RULESET_VERSION, QUERY_VERSION, PROMPT_VERSION, shas]).encode()).hexdigest()


def _slim(results: dict) -> dict:
    """What the narrator sees: results without SQL text."""
    out = json.loads(json.dumps(results, default=str))
    for r in out.get("results", []):
        r.pop("sql", None)
    return out


_NUM = re.compile(r"(?<![\w-])\d+(?:\.\d+)?(?![\w-])")


def postcheck(conn, answer_md: str, results: dict) -> dict:
    blob = json.dumps(results, default=str)
    known = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", blob)}
    text = re.sub(r"\b[A-Z]{2,}-[A-Z]?\d+\b", " ", answer_md)          # drop IDs like BH-D103, HG-E110
    text = re.sub(r"\bL\d+(?:[-–]\d+)?\b", " ", text)                    # drop line refs
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)                  # ISO dates
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)                      # clock times (checked via quotes)
    months = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
    text = re.sub(rf"\b\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?\s+{months}(?:\s+\d{{4}})?(?!\d)", " ", text)  # 26 January 2026
    text = re.sub(rf"\b{months}\s+\d{{1,2}}(?!\d)(?:\s*[-–]\s*\d{{1,2}}(?!\d))?(?:,\s*\d{{4}})?", " ", text)  # Jan 26–30, 2026
    unknown = sorted({n for n in _NUM.findall(text) if float(n) not in known}, key=float)
    # Citations: the pattern is built from the corpus's own document labels (any ID scheme or filename stem).
    labels = sorted({r[0] for r in conn.execute("SELECT doc_label FROM documents")}, key=len, reverse=True)
    label_re = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, labels)) + r")(?![\w-])") if labels else None
    cited = sorted({m.group(1) for m in label_re.finditer(answer_md)}) if label_re else []
    in_results = {lab for lab in cited if lab in blob}
    not_in_results = [c for c in cited if c not in in_results]
    # Things that look like document citations "(XYZ-123 L4)" but name no document in the corpus.
    known_ids = set(labels) | set(re.findall(r"[A-Z]{1,}-[A-Z]?\d+", blob))
    bad_docs = sorted({m for m in re.findall(r"\(([A-Za-z][\w.-]*\d)\s+L\d+", answer_md) if m not in known_ids})
    # Every line reference in a citation group must fall inside an evidence passage for that document.
    spans: dict[str, list[tuple[int, int]]] = {}
    for r in results.get("results", []):
        for ev in r.get("evidence", []):
            for p in ev["passages"]:
                a, _, b = p["lines"].partition("-")
                spans.setdefault(ev["doc_id"], []).append((int(a), int(b or a)))
    bad_lines = []
    if label_re:
        matches = list(label_re.finditer(answer_md))
        for i, m in enumerate(matches):
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(answer_md)
            seg = re.split(r"[);\]]", answer_md[m.end():seg_end], maxsplit=1)[0]
            for a, b in re.findall(r"L(\d+)(?:\s*[-–]\s*L?(\d+))?", seg):
                for ln in {int(a), int(b or a)}:
                    # a line citation must be backed by an evidence passage in the results; documents with no
                    # passages in the results cannot back any line reference
                    if not any(x <= ln <= y for x, y in spans.get(m.group(1), [])):
                        bad_lines.append(f"{m.group(1)} L{ln}")
    return {"numbers_not_in_results": unknown, "unknown_documents": bad_docs,
            "documents_not_in_results": not_in_results, "line_refs_outside_evidence": sorted(set(bad_lines)),
            "ok": not (unknown or bad_docs or bad_lines)}


def answer_question(question: str, *, db_path=None, use_cache: bool = True, qid: str | None = None) -> dict:
    conn = connect(db_path)
    key = hashlib.sha256((question + fingerprint(conn)).encode()).hexdigest()
    if use_cache:
        row = conn.execute("SELECT result_json FROM answer_cache WHERE cache_key=?", (key,)).fetchone()
        if row:
            t0 = time.monotonic()
            res = json.loads(row["result_json"])
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
    if not plan.steps:
        answer = {"answer_markdown": f"**Not answerable with the supported operations.** {plan.unsupported_reason}",
                  "unresolved": [], "caveats": None}
    else:
        nr = complete_json(NARRATOR_SYSTEM, f"Question:\n{question}\n\nComputed results (JSON):\n"
                           f"{json.dumps(_slim(results), indent=1, default=str)}", NarrativeOut, effort="medium")
        acc(nr)
        answer = nr.data.model_dump()
    t3 = time.monotonic()
    res = {
        "id": qid, "question": question, "plan": plan.model_dump(mode="json"), "plan_explain": plan.explain(),
        "results": results, "answer_markdown": answer["answer_markdown"], "unresolved": answer["unresolved"],
        "caveats": answer.get("caveats"), "postcheck": postcheck(conn, answer["answer_markdown"], results),
        "timings_ms": {"plan_llm": int((t1 - t0) * 1000), "execute": round((t2 - t1) * 1000, 2),
                       "narrate_llm": int((t3 - t2) * 1000), "total": int((t3 - t0) * 1000)},
        "llm": llm, "cached": False, "fingerprint": fingerprint(conn),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    conn.execute("INSERT OR REPLACE INTO answer_cache VALUES (?,?,?,?)",
                 (key, question, json.dumps(res, default=str), res["created_at"]))
    conn.commit()
    return res


def render_markdown(res: dict) -> str:
    lines = [f"# {res.get('id') or 'Answer'}", "", f"> {res['question']}", "", res["answer_markdown"], ""]
    if res.get("unresolved"):
        lines += ["## Not settled by the record", ""] + [f"- {u}" for u in res["unresolved"]] + [""]
    lines += ["## How this was computed", "", "```", res["plan_explain"], "```", ""]
    for r in res["results"].get("results", []):
        if r.get("calculation"):
            lines += [f"**{r['op']}**", ""] + [f"- {c}" for c in r["calculation"]] + [""]
    pc = res["postcheck"]
    lines += ["## Post-check", "", f"- numbers in the answer not found in computed results: {pc['numbers_not_in_results'] or 'none'}",
              f"- cited documents not in the corpus: {pc['unknown_documents'] or 'none'}",
              f"- line references outside the evidence passages: {pc['line_refs_outside_evidence'] or 'none'}", ""]
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


def verify_answers(*, db_path=None, rewrite: bool = True) -> list[dict]:
    """Re-execute every saved answer's QueryPlan against the current abstraction (no LLM) and confirm the results are
    identical to those the narrative was written from; re-run the post-check. Reproducibility check for reviewers."""
    from .db import connect_readonly
    conn, ro = connect(db_path), connect_readonly(db_path)
    report = []
    for p in sorted(OUT_DIR.glob("*.json")):
        res = json.loads(p.read_text())
        if "plan" not in res:
            continue
        plan = QueryPlan.model_validate(res["plan"])
        fresh = json.loads(json.dumps(execute_plan(ro, plan), default=str))
        same = json.dumps(fresh, sort_keys=True) == json.dumps(res["results"], sort_keys=True, default=str)
        pc = postcheck(conn, res["answer_markdown"], res["results"])
        report.append({"id": res.get("id"), "results_identical": same, "postcheck_ok": pc["ok"], "postcheck": pc})
        if rewrite:
            res["postcheck"] = pc
            p.write_text(json.dumps(res, indent=2, default=str))
            p.with_suffix(".md").write_text(render_markdown(res))
    return report


def answer_file(path: str, *, db_path=None, use_cache: bool = True) -> list[dict]:
    qs = json.loads(Path(path).read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for q in qs:
        res = answer_question(q["question"], db_path=db_path, use_cache=use_cache, qid=q.get("id"))
        res["id"] = q.get("id")
        (OUT_DIR / f"{q['id']}.json").write_text(json.dumps(res, indent=2, default=str))
        (OUT_DIR / f"{q['id']}.md").write_text(render_markdown(res))
        print(f"{q['id']}: total {res['timings_ms']} cached={res['cached']} postcheck_ok={res['postcheck']['ok']}")
        out.append(res)
    combined = [f"# Answers: {Path(path).name}", ""]
    for r in out:
        combined += [f"## {r['id']}", "", f"> {r['question']}", "", r["answer_markdown"], "",
                     f"_Details, plan, calculations and evidence: [{r['id']}.md]({r['id']}.md)_", ""]
    name = "ANSWERS.md" if Path(path).name == "questions.json" else f"ANSWERS_{Path(path).stem}.md"
    (OUT_DIR / name).write_text("\n".join(combined))
    return out
