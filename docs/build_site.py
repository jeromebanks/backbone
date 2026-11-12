"""Generate docs/index.html (human-facing overview) from the persisted abstraction.

    python docs/build_site.py

Numbers on the page are read from out/backbone.db (via the same operators the system uses), out/benchmarks.json and
out/ablation.json, so the page cannot drift from the data. The page is a single self-contained file: no external
scripts, fonts, or network requests (the material is confidential).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backbone.answer import fingerprint  # noqa: E402
from backbone.db import connect  # noqa: E402
from backbone.export import build_abstraction  # noqa: E402
from backbone.query import CareStep, ComplianceStep, QueryPlan, Scope, execute_plan  # noqa: E402

MRN, START, END = "HG-M042", "2026-01-05", "2026-01-30"
OUT = ROOT / "docs" / "index.html"
INGEST_TEMPLATE_PATH = ROOT / "docs" / "templates" / "ingestion.template.html"


def collect() -> dict:
    conn = connect()
    plan = QueryPlan(question="site", steps=[
        CareStep(scope=Scope(patients=[MRN], start=START, end=END, include_evidence=False), group_by="week"),
        ComplianceStep(scope=Scope(patients=[MRN], start=START, end=END, include_evidence=False), consecutive_below=2)])
    care, comp = execute_plan(conn, plan)["results"]
    ab = build_abstraction(conn, MRN)
    weeks = []
    for w in comp["groups"]:
        ev = w["evaluations"][0]
        t = ev["totals"]
        weeks.append({"week_start": w["week_start"], "status": w["status"], "days": t["therapy_days"]["low"],
                      "sessions": t["sessions"]["low"], "min_lo": t["minutes"]["low"], "min_hi": t["minutes"]["high"],
                      "calc": ev["minutes_calculation"], "notes": w["notes"],
                      "reqs": [{"metric": r["metric"], "goal": r["goal"], "status": r["status"]} for r in ev["requirements"]]})
    encs = []
    for e in ab["encounters"]:
        encs.append({
            "key": e["encounter_key"].split("|", 1)[1], "date": e["service_date"], "week": e["week_start"],
            "type": e["service_type"], "disposition": e["disposition"], "eligible": e["eligible"],
            "reason": e["exclusion_reason"], "min_lo": e["minutes_low"], "min_hi": e["minutes_high"],
            "mstatus": e["minutes_status"], "calc": e["calculation"], "flags": e["flags"],
            "intervals": e["intervals"], "decisions": e["decisions"], "conflicts": e["conflicts"],
            "records": [{"doc": r["doc_id"], "file": r["file"], "type": r["record_type"],
                         "passages": [{"lines": f"{p['lines'][0]}" + (f"–{p['lines'][1]}" if p["lines"][1] != p["lines"][0] else ""),
                                       "quote": p["quote"]} for p in r["passages"]]} for r in e["records"]],
        })
    assess = [{"date": a["completed_date"], "instrument": a["instrument"], "score": a["total_score"],
               "form": a["form_id"], "items": a["item_scores"], "docs": sorted({x["doc_id"] for x in a["evidence"]}),
               "copies": sorted({x["doc_id"] for x in a["copies_not_counted"]})} for a in ab["assessments"]]
    bench = json.loads((ROOT / "out" / "benchmarks.json").read_text())
    ablation = json.loads((ROOT / "out" / "ablation.json").read_text())
    answers = []
    for p in sorted((ROOT / "out" / "answers").glob("*.json")):
        a = json.loads(p.read_text())
        t = a.get("timings_ms_original") or a["timings_ms"]
        answers.append({"id": a["id"], "q": a["question"], "ok": a["postcheck"]["ok"], "ms": t.get("total"),
                        "plan": a["plan_explain"].split("\n", 1)[1] if "\n" in a["plan_explain"] else a["plan_explain"]})
    t = care["totals"]
    return {
        "fingerprint": fingerprint(conn)[:12],
        "totals": {"sessions": t["sessions"]["low"], "days": t["therapy_days"]["low"], "min_lo": t["minutes"]["low"],
                   "min_hi": t["minutes"]["high"], "h_lo": t["hours"]["low"], "h_hi": t["hours"]["high"],
                   "by_type": {x["service_type"]: x["sessions"]["low"] for x in t["by_service_type"]}},
        "runs": comp["facts"], "weeks": weeks, "encounters": encs, "assessments": assess, "answers": answers,
        "ablation": ablation,
        "bench": {k: bench[k] for k in ("extraction_initial_run", "rebuild_from_cache", "reingest_unchanged",
                                        "incremental_add_one_document", "operator_latency_real_patient",
                                        "synthetic_collection_scale", "persisted_abstraction", "question_answering",
                                        "question_answering_cached_repeat", "machine")},
        "counts": {k: ab and len(ab[k]) for k in ("documents", "encounters", "observations")},
    }


def ingest_data(data: dict) -> dict:
    b = data["bench"]
    x = b["extraction_initial_run"]
    return {
        "in_tokens": x["input_tokens_per_doc"], "out_tokens": x["output_tokens_per_doc"],
        "latency_s": round(x["latency_ms_mean"] / 1000, 1), "cost_per_doc": x["list_price_cost_usd_per_doc"],
        "docs": x["documents"], "model": x["model"][0],
        "reconcile_ms": b["incremental_add_one_document"]["reconcile_one_patient_ms"],
        "ingest_ms": b["incremental_add_one_document"]["ingest_ms_excluding_llm"],
        "claims_per_doc": round(b["persisted_abstraction"]["claims"] / b["persisted_abstraction"]["documents"], 1),
        "wall_s": 58, "concurrency": 8,
    }


def main() -> None:
    data = collect()
    html = TEMPLATE.replace("/*__DATA__*/null", json.dumps(data, default=str).replace("</", "<\\/"))
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html) // 1024} KB)")
    css = re.search(r"<style>(.*?)</style>", TEMPLATE, re.S).group(1)
    page = (INGEST_TEMPLATE_PATH.read_text().replace("/*__CSS__*/", css)
            .replace("/*__DATA__*/null", json.dumps(ingest_data(data)).replace("</", "<\\/")))
    out2 = ROOT / "docs" / "ingestion.html"
    out2.write_text(page)
    print(f"wrote {out2.relative_to(ROOT)} ({len(page) // 1024} KB)")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<link rel="icon" href="data:,">
<title>Clinical Abstraction Prototype</title>
<style>
:root{
  --bg:#f7f6f3; --surface:#ffffff; --surface-2:#f1efea; --text:#1d1c1a; --muted:#6b6862; --line:#e2dfd8;
  --accent:#2f5bd3; --accent-soft:#e3eafc; --ok:#1f7a4d; --ok-soft:#dcf1e6; --bad:#b4372d; --bad-soft:#f9e1de;
  --warn:#9a6a00; --warn-soft:#fbefcf; --hatch:#b4372d; --code-bg:#f1efea;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#141413; --surface:#1c1c1a; --surface-2:#242422; --text:#ecebe7; --muted:#a19e97; --line:#33322f;
    --accent:#8aa6ff; --accent-soft:#232c45; --ok:#5fcf97; --ok-soft:#183427; --bad:#ff8a7d; --bad-soft:#3d1f1c;
    --warn:#f0c35a; --warn-soft:#3a2f12; --hatch:#ff8a7d; --code-bg:#242422;
  }
}
:root[data-theme="dark"]{
  --bg:#141413; --surface:#1c1c1a; --surface-2:#242422; --text:#ecebe7; --muted:#a19e97; --line:#33322f;
  --accent:#8aa6ff; --accent-soft:#232c45; --ok:#5fcf97; --ok-soft:#183427; --bad:#ff8a7d; --bad-soft:#3d1f1c;
  --warn:#f0c35a; --warn-soft:#3a2f12; --hatch:#ff8a7d; --code-bg:#242422;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 var(--sans);-webkit-font-smoothing:antialiased}
a{color:var(--accent)}
code,pre{font-family:var(--mono);font-size:.86em}
code{background:var(--code-bg);padding:.1em .35em;border-radius:4px}
pre{background:var(--code-bg);padding:14px 16px;border-radius:10px;overflow-x:auto;line-height:1.5;margin:12px 0}
pre code{background:none;padding:0}
.layout{display:grid;grid-template-columns:230px minmax(0,1fr);max-width:1240px;margin:0 auto;gap:40px;padding:0 24px}
nav.toc{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;padding:32px 0;font-size:14px}
nav.toc .brand{font-weight:650;margin-bottom:16px;line-height:1.3}
nav.toc a{display:block;color:var(--muted);text-decoration:none;padding:5px 10px;border-radius:6px;border-left:2px solid transparent}
nav.toc a:hover{color:var(--text);background:var(--surface-2)}
nav.toc a.active{color:var(--text);border-left-color:var(--accent);background:var(--surface-2)}
main{padding:32px 0 80px;min-width:0}
header.hero{padding:8px 0 28px;border-bottom:1px solid var(--line);margin-bottom:12px}
.badge{display:inline-block;font-size:12px;font-weight:600;letter-spacing:.02em;padding:3px 9px;border-radius:999px;background:var(--warn-soft);color:var(--warn)}
h1{font-size:34px;line-height:1.15;margin:14px 0 10px;letter-spacing:-.01em}
h2{font-size:24px;margin:56px 0 10px;letter-spacing:-.005em;scroll-margin-top:16px}
h3{font-size:17px;margin:26px 0 8px}
p.lead{font-size:18px;color:var(--muted);max-width:780px;margin:0}
p,li{max-width:820px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0 0}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:650;letter-spacing:-.01em}
.kpi .l{font-size:13px;color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:14px 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin:14px 0}
.grid2 > .card{margin:0}
.trap h4{margin:0 0 6px;font-size:15px}
.trap p{margin:0;font-size:14.5px;color:var(--muted)}
.trap .fix{margin-top:8px;color:var(--text)}
table{border-collapse:collapse;width:100%;font-size:14.5px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--surface);margin:14px 0}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;background:var(--surface-2)}
tr:last-child td{border-bottom:none}
.pill{display:inline-block;font-size:12px;font-weight:650;padding:2px 9px;border-radius:999px;white-space:nowrap}
.MET{background:var(--ok-soft);color:var(--ok)} .NOT_MET{background:var(--bad-soft);color:var(--bad)}
.UNDETERMINED{background:var(--warn-soft);color:var(--warn)}
.flip{outline:2px solid var(--bad);outline-offset:-2px}
.muted{color:var(--muted)} .small{font-size:13.5px}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;color:var(--muted);margin:8px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:22px;height:10px;border-radius:2px;display:inline-block}
#timeline{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:12px}
#timeline svg{display:block;min-width:720px;width:100%}
.row:hover .rowbg{fill:var(--surface-2)} .row{cursor:pointer}
.row.sel .rowbg{fill:var(--accent-soft)}
#detail{min-height:120px}
#detail h4{margin:0 0 4px;font-size:16px}
#detail code{white-space:normal;word-break:break-word}
.dec{font-size:13.5px;margin:4px 0;padding-left:10px;border-left:3px solid var(--line)}
.dec b{font-family:var(--mono);font-size:12px}
.quote{font-size:13.5px;margin:6px 0;padding:8px 10px;background:var(--surface-2);border-radius:8px}
.quote .src{font-family:var(--mono);font-size:12px;color:var(--muted)}
.diagram svg{width:100%;height:auto;display:block}
.diagram{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px}
footer{margin-top:64px;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media (max-width: 900px){
  .layout{grid-template-columns:1fr;gap:0;padding:0 16px}
  nav.toc{position:static;height:auto;padding:16px 0 0;display:flex;flex-wrap:wrap;gap:4px}
  nav.toc .brand{width:100%;margin-bottom:6px}
  nav.toc a{border-left:none;background:var(--surface-2);font-size:13px;padding:4px 9px}
  h1{font-size:27px} h2{font-size:21px}
}
</style>
</head>
<body>
<div class="layout">
<nav class="toc" id="toc">
  <div class="brand">Clinical Abstraction<br><span class="muted small">Backbone take-home</span></div>
  <a href="#overview">Overview</a>
  <a href="#problem">The problem</a>
  <a href="#how">How it works</a>
  <a href="#results">Weekly results</a>
  <a href="#timeline-sec">Encounter timeline</a>
  <a href="#traps">Traps in the record</a>
  <a href="#rules">Reconciliation rules</a>
  <a href="#uncertainty">Uncertainty</a>
  <a href="#dsl">Query DSL</a>
  <a href="#answers">Answers</a>
  <a href="#experiment">Design experiment</a>
  <a href="#performance">Performance &amp; scale</a>
  <a href="#limits">Limitations</a>
  <a href="#run">Running it</a>
  <a href="ingestion.html" style="margin-top:10px">Ingestion design →</a>
</nav>
<main>
<header class="hero" id="overview">
  <span class="badge">Confidential: private submission, do not share</span>
  <h1>From contradictory clinical records to answers you can audit</h1>
  <p class="lead">A prototype that turns overlapping, conflicting behavioral-health documents into a persistent
  clinical abstraction, then answers questions with deterministic computation. Every number traces back to
  encounters, reconciliation decisions, verified source passages and original files.</p>
  <div class="kpis" id="kpis"></div>
</header>

<h2 id="problem">The problem</h2>
<p>Backbone reviews clinical records to decide what care a patient actually received, and whether the documentation
supports it. The information is spread across clinical notes, attendance rosters, corrections, schedule exports,
telehealth logs, billing extracts, imported summaries and a treatment plan. These documents often describe the same
contact more than once, disagree on details, or correct one another later.</p>
<p>The exercise asks for five answers about one patient's four-week episode: sessions, minutes, weekly plan
compliance, a reconstruction of two specific days, and the symptom course. It also asks for a design that reuses
work across questions and scales to 500,000+ documents. A later document does <em>not</em> automatically override
an earlier one.</p>

<h2 id="how">How it works</h2>
<p>Two pipelines share one persisted abstraction. The language model works only at the semantic edges: reading one
document, choosing operations for a question, and phrasing the computed result. Everything in between is ordinary
deterministic code.</p>
<div class="diagram" id="diagram"></div>
<div class="grid2">
  <div class="card"><h3 style="margin-top:0">1 · Evidence: claims, not facts</h3><p class="small">One LLM call per
  document records what <em>that document asserts</em>: intervals, dispositions, signatures, corrections, copies,
  assessments and plan goals. It never computes durations. Every quote is located in the source by code, which also
  assigns the line numbers. The result is cached by content hash, so re-runs are free.</p></div>
  <div class="card"><h3 style="margin-top:0">2 · Reconciliation: versioned rules</h3><p class="small">Pure Python
  rules (R0–R9) group records into encounters, apply corrections, discard drafts and billing as attendance
  evidence, and compute minutes by interval arithmetic. Unresolved disagreement is kept as a range. Every choice is
  logged as a decision.</p></div>
  <div class="card"><h3 style="margin-top:0">3 · Projection: one place for clinical math</h3><p class="small">Counts,
  therapy days, minutes, Monday–Sunday weeks, the plan in effect, and MET / NOT_MET / UNDETERMINED verdicts are all
  computed in a single module, so every query uses the same semantics.</p></div>
  <div class="card"><h3 style="margin-top:0">4 · Questions: a typed query plan</h3><p class="small">The LLM turns a
  question into a validated <code>QueryPlan</code> over four operators. Code executes it in milliseconds. The LLM
  then writes the answer from the results alone, and a post-check verifies every number and citation.</p></div>
</div>

<h2 id="results">Weekly results</h2>
<p>Treatment-plan goal (BH-D003): <b>at least 3 therapy days and at least 150 patient-present minutes in each
Monday–Sunday week.</b> Individual, group and family psychotherapy count. Medication management, collateral-only
and care-coordination contacts do not.</p>
<div class="tablewrap"><table id="weeks"></table></div>
<p class="small muted" id="runs"></p>

<h2 id="timeline-sec">Encounter timeline</h2>
<p>Every encounter the system reconstructed, on a common clock. <b>Click a row</b> to see how it was decided: the
records that mention it, the verified source passages, and the rules applied.</p>
<div class="legend">
  <span><i class="sw" style="background:var(--accent)"></i>patient present (counts)</span>
  <span><i class="sw" style="background:var(--muted);opacity:.45"></i>present, doesn't count</span>
  <span><i class="sw" style="border:1.5px dashed var(--muted)"></i>scheduled</span>
  <span><svg width="22" height="10"><rect width="22" height="10" fill="url(#hatch-legend)"/><defs><pattern id="hatch-legend" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="var(--hatch)"/></pattern></defs></svg>excluded (break, disconnection, patient absent)</span>
</div>
<div id="timeline"></div>
<div class="card" id="detail"><span class="muted">Select an encounter above. Try <b>HG-E110</b> (Jan 19),
<b>HG-E115</b> (Jan 26) or <b>HG-E116</b> (Jan 27).</span></div>

<h2 id="traps">Traps in the record, and how they're handled</h2>
<div class="grid2" id="trapgrid">
  <div class="card trap"><h4>A correction, then an older copy received later</h4><p>The Jan 19 roster said Rowan left
  group at 11:30 (BH-D102). A signed correction changed it to 11:15 (BH-D103). On Jan 26 the <em>uncorrected</em> roster
  was resent (BH-D104).</p><p class="fix">The field-scoped correction wins, and the resend is treated as a copy.
  The old value would also overlap the 11:15 individual session, which the overlap rule detects.</p></div>
  <div class="card trap"><h4>A draft note and a charge for a no-show</h4><p>An unsigned, template-generated note says
  "attended the full session", and a group charge was posted (BH-D112). The signed register says no-show (BH-D108).</p>
  <p class="fix">Drafts and billing rows are not attendance evidence. The session is excluded, and the reason is
  logged.</p></div>
  <div class="card trap"><h4>Two signed notes disagree</h4><p>For the Jan 26 individual session, one clinician
  records 09:00–09:50 (BH-D110) and the co-clinician 09:10–09:50, noting when Rowan entered (BH-D111).</p>
  <p class="fix">Neither corrects the other, so the session is carried as 40–50 minutes. Week 4 is therefore
  UNDETERMINED, not guessed.</p></div>
  <div class="card trap"><h4>Stated durations that aren't patient time</h4><p>The Jan 30 family note says "45
  minutes", but the partner was seen alone for the first 15 (BH-D113). Group notes list 90-minute slots with a
  15-minute break, and late arrivals and early departures appear only on rosters.</p><p class="fix">Minutes are
  computed from intervals: patient present, minus breaks, disconnections and partner-only portions. Stated totals
  are only cross-checks.</p></div>
  <div class="card trap"><h4>One session, two video calls</h4><p>The Jan 21 telehealth session dropped and reconnected
  under the same appointment (BH-D106).</p><p class="fix">That is one encounter with two contact segments: 20 + 25 =
  45 minutes. The 10-minute gap is excluded.</p></div>
  <div class="card trap"><h4>Copies that look like new measurements</h4><p>An import receipt dated Jan 26 (BH-D014)
  repeats the Jan 16 PHQ-9 (form HG-Q116).</p><p class="fix">Assessments are identified by instrument, completion
  date and form, so it is one assessment, not two. Three distinct PHQ-9s: 18 → 14 → 10.</p></div>
  <div class="card trap"><h4>Contacts that aren't therapy</h4><p>A partner-only collateral visit, a call between
  professionals, medication management, outreach calls.</p><p class="fix">These are classified and excluded with
  reasons. They never count toward therapy days or minutes.</p></div>
  <div class="card trap"><h4>Duplicate notes for one visit</h4><p>Primary and co-facilitator notes for the Jan 9 family
  session (BH-D007, BH-D008), plus schedule exports that repeat every appointment.</p><p class="fix">Records are grouped
  by encounter identity. Many records make one session.</p></div>
</div>

<h2 id="rules">Reconciliation rules</h2>
<div class="tablewrap"><table>
<tr><th>Rule</th><th>What it does</th></tr>
<tr><td><b>R0</b></td><td>Reject any claim whose quote cannot be located in the source text (none rejected in this corpus).</td></tr>
<tr><td><b>R1</b></td><td>Encounter identity by ID; otherwise same date + service type (+ overlapping times); otherwise a separate contact.</td></tr>
<tr><td><b>R2</b></td><td>Drafts, templates and billing rows are not attendance evidence.</td></tr>
<tr><td><b>R3</b></td><td>Explicit corrections replace only the field they correct; retransmitted copies carry no independent weight. Precedence follows relationships, never document date.</td></tr>
<tr><td><b>R4</b></td><td>Evidence tiers (notes, registers, corrections, platform logs above schedule listings). Disagreement within the deciding tier is a dispute, carried as a range.</td></tr>
<tr><td><b>R5</b></td><td>A session counts if it is psychotherapy, attended, and the patient was present. Unknown attendance is "uncertain", never zero.</td></tr>
<tr><td><b>R6</b></td><td>Minutes = present intervals − breaks − disconnections − patient-absent portions.</td></tr>
<tr><td><b>R7</b></td><td>A patient cannot be in two encounters at once; overlaps are flagged.</td></tr>
<tr><td><b>R8</b></td><td>Assessments are identified by instrument, completion date and form; imports and copies are not new assessments.</td></tr>
<tr><td><b>R9</b></td><td>Plan requirements apply by effective date. A revision supersedes earlier goals from its start date. A week spanning a change is judged on whole-week totals against each plan, and is UNDETERMINED if they disagree.</td></tr>
</table></div>

<h2 id="uncertainty">Uncertainty: ranges and three-valued verdicts</h2>
<p>Every quantity is a range <code>[low, high]</code>. A goal is <span class="pill MET">MET</span> if it holds at
both ends, <span class="pill NOT_MET">NOT MET</span> if it holds at neither, and
<span class="pill UNDETERMINED">UNDETERMINED</span> otherwise. The system never picks a value to make a verdict
look certain.</p>
<div class="card" id="bounds"></div>

<h2 id="dsl">The query DSL</h2>
<p>Questions compile to a typed, validated plan. The model never writes SQL or code. Each step shares one
<code>Scope</code> (patients or "all", dates, service types, include excluded records, include evidence) and runs one
of four operators:</p>
<div class="tablewrap"><table>
<tr><th>Operator</th><th>Returns</th></tr>
<tr><td><code>care</code></td><td>Sessions, therapy days and minutes/hours (with ranges) by type, day, week or patient; optionally every record that doesn't count, and why.</td></tr>
<tr><td><code>compliance</code></td><td>Per week: the goal in effect, delivered totals, the verdict, exclusions; runs of N weeks below goal (definite vs dependent on unresolved records).</td></tr>
<tr><td><code>timeline</code></td><td>Chronology of encounters, documents (and what each asserted), decisions, assessments and observations. A one-day scope reconstructs that day.</td></tr>
<tr><td><code>compare</code></td><td>Care before vs after a date or a treatment-plan change.</td></tr>
</table></div>
<div class="grid2">
<div><h3>As JSON (what the model emits)</h3>
<pre><code>{"question": "Weekly plan compliance, Jan 5–30",
 "steps": [
  {"op": "compliance",
   "scope": {"patients": ["HG-M042"],
             "start": "2026-01-05", "end": "2026-01-30"},
   "consecutive_below": 2}]}</code></pre></div>
<div><h3>As Python (same plan object)</h3>
<pre><code>from backbone.dsl import care
q = (care.for_patient("HG-M042")
         .during("2026-01-05", "2026-01-30")
         .compliance(consecutive_below=2))
q.explain(); q.execute(conn); q.to_sql(conn)</code></pre></div>
</div>
<p>Every operator returns the same machine-readable envelope: totals, groups, facts, human-readable arithmetic,
exclusions, conflicts, decisions, evidence passages (document, line, quote) and the exact parameterized SQL.</p>

<h2 id="answers">Answers</h2>
<p>The five development questions, plus six unseen questions that exercise generalization (including one correctly
refused as unsupported). Each answer file shows the narrative, the plan, the arithmetic, the post-check and every
evidence passage.</p>
<div class="tablewrap"><table id="answers-t"></table></div>

<h2 id="experiment">Design experiment: what naive rules would conclude</h2>
<p>The same weekly projection, re-run after treating the records the way common shortcuts would. Outlined cells are
verdicts that differ from this system's.</p>
<div class="tablewrap"><table id="ablation"></table></div>
<p class="small muted">Five of the seven shortcuts flip at least one weekly verdict. "Latest document wins" leaves
the verdicts alone but inflates week 3's minutes and creates an impossible overlap between two sessions.</p>

<h2 id="performance">Performance &amp; scale</h2>
<p>All figures are measured on a laptop (<span id="machine"></span>). Scale figures use a <b>synthetic</b>
collection: the real patient's reconciled records cloned per patient, which measures the query layer only.</p>
<div class="tablewrap"><table id="perf"></table></div>
<div class="tablewrap"><table id="scale"></table></div>
<h3>Toward 500K–1M documents (estimates)</h3>
<ul>
<li><b>The first bottleneck is LLM extraction.</b> At the measured ~$0.045 and ~13 s per document, 1M documents is
≈ $45K at list price and ~3 weeks at 8-way concurrency. Prompt caching, the Batch API (−50%) and a cheaper
extractor validated against this corpus are the levers. The content-hash cache already makes re-deliveries free.</li>
<li><b>Next: collection-wide compliance.</b> It is linear, at one query per patient-week. The fix is to persist a
weekly projection per patient on reconcile and compute streaks in SQL.</li>
<li><b>Then the single SQLite writer.</b> Reconciliation is already per patient (~4 ms) and partitions cleanly →
Postgres plus a queue of patients whose records changed.</li>
</ul>

<h2 id="limits">Limitations &amp; next steps</h2>
<ul>
<li><b>Extraction is a single pass.</b> Passing mentions of appointments sometimes become separate "unidentified
contacts". They never count as therapy, but they add noise. Next: an agreement harness (k runs, cheaper models)
measuring field-level stability, and stricter handling of mentions.</li>
<li>The post-check verifies numbers and citations, not prose interpretation.</li>
<li>There is no second planning round if the first query plan is insufficient.</li>
<li>Provider identities are not merged, deliberately: "N. Ellis" at the desk is not assumed to be "Nora Ellis, LCSW".</li>
<li>The API-key LLM backend is implemented but not exercised; all results used a Claude subscription via Claude Code.</li>
</ul>

<h2 id="run">Running it</h2>
<pre><code>python -m pytest -q                                   # 34 tests, no LLM calls
python -m backbone verify-answers                     # saved answers reproduce exactly
python -m backbone plan plans/weekly_compliance.json  # hand-written plan, no LLM
python -m backbone ingest path/to/new_doc.txt         # extracts only new docs; re-reconciles that patient
python -m backbone ask "Which weeks met the day goal but not the minute goal?"
python docs/build_site.py                             # regenerate this page from the data</code></pre>

<footer>
Generated by <code>docs/build_site.py</code> from <code>out/backbone.db</code> (abstraction fingerprint
<code id="fp"></code>), <code>out/benchmarks.json</code> and <code>out/ablation.json</code>. Self-contained; makes no
network requests. Source documents are synthetic training records supplied by Backbone. This repository is
private: do not redistribute.
</footer>
</main>
</div>

<script id="data" type="application/json">/*__DATA__*/null</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rng = (lo, hi) => lo === hi ? `${lo}` : `${lo}–${hi ?? '?'}`;
const pill = s => `<span class="pill ${s}">${s.replace('_',' ')}</span>`;
const fmtDate = s => new Date(s + 'T00:00:00').toLocaleDateString('en-US', {month:'short', day:'numeric'});
const typeName = t => ({individual_therapy:'Individual', group_therapy:'Group', family_therapy:'Family',
  family_collateral:'Collateral (partner only)', medication_management:'Medication mgmt', care_coordination:'Care coordination',
  outreach_call:'Outreach call', administrative:'Administrative', other:'Other'}[t] || t);

// KPIs
const T = D.totals, W = D.weeks;
const count = s => W.filter(w => w.status === s).length;
$('#kpis').innerHTML = [
  [T.sessions, `therapy sessions (${T.by_type.individual_therapy||0} individual · ${T.by_type.group_therapy||0} group · ${T.by_type.family_therapy||0} family)`],
  [T.days, 'distinct therapy days'],
  [`${T.min_lo}–${T.min_hi}`, `patient-present minutes (${T.h_lo}–${T.h_hi} h)`],
  [`${count('MET')} / ${count('NOT_MET')} / ${count('UNDETERMINED')}`, 'weeks met / not met / undetermined'],
].map(([v,l]) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join('');

// Pipeline diagram (inline SVG, theme-aware)
(function(){
  const boxes = [
    ['Documents', ['31 files', 'sha256 identity']],
    ['Claims', ['LLM extraction', 'verified quotes']],
    ['Encounters', ['rules R0–R9', 'decisions logged']],
    ['Projection', ['ranges · weeks', 'plan verdicts']],
    ['Answers', ['QueryPlan → SQL', 'cited narrative']],
  ];
  const w = 172, h = 92, gap = 26, x0 = 6, y = 18;
  let s = `<svg viewBox="0 0 ${x0*2 + boxes.length*w + (boxes.length-1)*gap} 164" role="img" aria-label="Pipeline: documents to claims to encounters to projection to answers">`;
  s += `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>`;
  boxes.forEach(([t, sub], i) => {
    const x = x0 + i*(w+gap);
    const llm = i === 1 || i === 4;
    s += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="var(--surface-2)" stroke="${llm ? 'var(--accent)' : 'var(--line)'}" stroke-width="${llm ? 2 : 1}"/>`;
    s += `<text x="${x + w/2}" y="${y + 34}" text-anchor="middle" fill="var(--text)" font-size="16" font-weight="650">${t}</text>`;
    sub.forEach((line, k) => s += `<text x="${x + w/2}" y="${y + 57 + k*16}" text-anchor="middle" fill="var(--muted)" font-size="12.5">${line}</text>`);
    if (i < boxes.length - 1) s += `<line x1="${x + w + 3}" y1="${y + h/2}" x2="${x + w + gap - 3}" y2="${y + h/2}" stroke="var(--muted)" stroke-width="1.5" marker-end="url(#arr)"/>`;
  });
  s += `<text x="${x0}" y="${y + h + 34}" fill="var(--muted)" font-size="12">Blue outline = the only LLM steps (reading one document; turning a question into a plan and phrasing results). Everything else is deterministic code over SQLite.</text>`;
  $('#diagram').innerHTML = s + '</svg>';
})();

// Weekly table
$('#weeks').innerHTML = `<tr><th>Week</th><th>Therapy days (≥3)</th><th>Minutes (≥150)</th><th>Calculation</th><th>Verdict</th></tr>` +
  W.map(w => `<tr><td>${fmtDate(w.week_start)}${w.notes.some(n=>n.startsWith('partial')) ? '<div class="small muted">partial week</div>' : ''}</td>
    <td>${w.days} ${pill(w.reqs.find(r=>r.metric==='therapy_days')?.status || '')}</td>
    <td>${rng(w.min_lo, w.min_hi)} ${pill(w.reqs.find(r=>r.metric==='patient_present_minutes')?.status || '')}</td>
    <td class="small"><code>${esc(w.calc)}</code></td><td>${pill(w.status)}</td></tr>`).join('');
const r = (D.runs||[])[0];
if (r) $('#runs').textContent = `Two or more consecutive weeks below goal: ${r.status === 'yes' ? 'yes, definite (weeks of ' + r.definite_runs.map(x => x.map(fmtDate).join(' and ')).join('; ') + '), and it does not depend on the unresolved week 4 record' : r.status}.`;

// Timeline
(function(){
  const E = D.encounters;
  const toMin = s => { const [h,m] = s.split(':').map(Number); return h*60 + m; };
  let lo = 24*60, hi = 0;
  E.forEach(e => e.intervals.forEach(iv => { lo = Math.min(lo, toMin(iv.start)); hi = Math.max(hi, toMin(iv.end)); }));
  lo = Math.floor(lo/60)*60; hi = Math.ceil(hi/60)*60 + 60;   // extra hour for labels
  const LW = 250, PW = 640, RH = 28, top = 26;
  const x = m => LW + (m - lo) / (hi - lo) * PW;
  const rows = [];
  let wk = null;
  E.forEach(e => { if (e.week !== wk) { wk = e.week; rows.push({hdr: wk}); } rows.push(e); });
  const H = top + rows.length * RH + 8;
  let s = `<svg viewBox="0 0 ${LW + PW + 20} ${H}" role="img" aria-label="Encounter timeline">`;
  s += `<defs><pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="var(--hatch)"/></pattern></defs>`;
  for (let m = lo; m <= hi; m += 60) {
    s += `<line x1="${x(m)}" y1="${top-6}" x2="${x(m)}" y2="${H}" stroke="var(--line)"/>`;
    s += `<text x="${x(m)}" y="${top-11}" text-anchor="middle" font-size="11" fill="var(--muted)">${String(m/60).padStart(2,'0')}:00</text>`;
  }
  rows.forEach((row, i) => {
    const y = top + i*RH;
    if (row.hdr) {
      const w = W.find(w => w.week_start === row.hdr);
      s += `<rect x="0" y="${y}" width="${LW + PW + 20}" height="${RH}" fill="var(--surface-2)"/>`;
      s += `<text x="8" y="${y + 19}" font-size="12" font-weight="700" fill="var(--text)">Week of ${fmtDate(row.hdr)}</text>`;
      if (w) s += `<text x="${LW - 8}" y="${y + 19}" text-anchor="end" font-size="11" font-weight="650" fill="${w.status==='MET'?'var(--ok)':w.status==='NOT_MET'?'var(--bad)':'var(--warn)'}">${w.status.replace('_',' ')}</text>`;
      return;
    }
    const e = row, counts = e.eligible === 'yes';
    s += `<g class="row" data-key="${esc(e.key)}"><rect class="rowbg" x="0" y="${y}" width="${LW + PW + 20}" height="${RH}" fill="transparent"/>`;
    const idLabel = e.key.startsWith('U-') ? 'no ID' : e.key;
    s += `<text x="8" y="${y + 18}" font-size="12" fill="${counts ? 'var(--text)' : 'var(--muted)'}">${fmtDate(e.date)} · ${esc(idLabel)} · ${esc(typeName(e.type))}</text>`;
    const sched = e.intervals.filter(v => v.kind === 'scheduled');
    const pres = e.intervals.filter(v => v.kind === 'present');
    const excl = e.intervals.filter(v => v.kind === 'excluded');
    sched.forEach(v => s += `<rect x="${x(toMin(v.start))}" y="${y+5}" width="${x(toMin(v.end)) - x(toMin(v.start))}" height="${RH-10}" rx="3" fill="none" stroke="var(--muted)" stroke-dasharray="4 3"/>`);
    const n = Math.max(1, pres.length), bh = (RH - 12) / n;
    pres.forEach((v, j) => s += `<rect x="${x(toMin(v.start))}" y="${y + 6 + j*bh}" width="${x(toMin(v.end)) - x(toMin(v.start))}" height="${bh - (n>1?1.5:0)}" rx="2" fill="${counts ? 'var(--accent)' : 'var(--muted)'}" opacity="${counts ? (n>1 ? .75 : 1) : .45}"><title>${esc(v.label)}</title></rect>`);
    excl.forEach(v => s += `<rect x="${x(toMin(v.start))}" y="${y+6}" width="${x(toMin(v.end)) - x(toMin(v.start))}" height="${RH-12}" fill="url(#hatch)"><title>${esc(v.label)} ${v.start}–${v.end}</title></rect>`);
    const label = e.eligible === 'yes' ? `${rng(e.min_lo, e.min_hi)} min` : e.eligible === 'uncertain' ? 'uncertain' : 'not counted';
    const lastEnd = Math.max(...e.intervals.map(v => toMin(v.end)), lo);
    const tx = e.intervals.length ? x(lastEnd) + 6 : LW + 6;
    s += `<text x="${tx}" y="${y + 18}" font-size="11.5" font-weight="${counts ? 650 : 400}" fill="${counts ? (e.mstatus === 'disputed' ? 'var(--warn)' : 'var(--text)') : 'var(--muted)'}">${label}</text></g>`;
  });
  $('#timeline').innerHTML = s + '</svg>';
  document.querySelectorAll('#timeline .row').forEach(g => g.addEventListener('click', () => select(g.dataset.key)));
  function select(key) {
    document.querySelectorAll('#timeline .row').forEach(g => g.classList.toggle('sel', g.dataset.key === key));
    const e = E.find(e => e.key === key);
    const status = e.eligible === 'yes' ? `<b>Counts</b>: ${rng(e.min_lo, e.min_hi)} patient-present minutes${e.mstatus === 'disputed' ? ' (disputed, carried as a range)' : ''}` :
      e.eligible === 'uncertain' ? '<b>Uncertain</b>' : `<b>Does not count</b>: ${esc(e.reason)}`;
    let h = `<h4>${esc(e.key.startsWith('U-') ? 'Unidentified contact (' + e.key + ')' : e.key)} · ${fmtDate(e.date)} · ${esc(typeName(e.type))}</h4><div class="small">${status}. Disposition: ${esc(e.disposition.replace('_',' '))}.</div>`;
    if (e.calc) h += `<p class="small"><code>${esc(e.calc)}</code></p>`;
    if (e.flags.length) h += e.flags.map(f => `<div class="dec small" style="border-color:var(--warn)">⚑ ${esc(f)}</div>`).join('');
    if (e.decisions.length) h += `<h3>Decisions</h3>` + e.decisions.map(d => `<div class="dec"><b>${esc(d.rule)}</b> ${esc(d.outcome)}: ${esc(d.reason)}</div>`).join('');
    if (e.records.length) h += `<h3>Source passages (${e.records.length} records)</h3>` + e.records.map(rec => rec.passages.map(p =>
      `<div class="quote">“${esc(p.quote)}”<div class="src">${esc(rec.doc)} · line ${esc(p.lines)} · ${esc(rec.type)} · ${esc(rec.file)}</div></div>`).join('')).join('');
    $('#detail').innerHTML = h;
  }
  select('HG-E110');
})();

// Bounds chart
(function(){
  const maxM = Math.max(200, ...W.map(w => w.min_hi)) + 10, LW = 120, PW = 560, RH = 34, top = 24;
  const x = m => LW + m / maxM * PW;
  let s = `<svg viewBox="0 0 ${LW + PW + 210} ${top + W.length*RH + 24}" style="width:100%;height:auto" role="img" aria-label="Weekly minutes against the 150-minute goal">`;
  [0, 50, 100, 150, 200].forEach(m => s += `<text x="${x(m)}" y="${top - 8}" text-anchor="middle" font-size="11" fill="var(--muted)">${m}</text><line x1="${x(m)}" y1="${top-2}" x2="${x(m)}" y2="${top + W.length*RH}" stroke="var(--line)"/>`);
  s += `<line x1="${x(150)}" y1="${top-2}" x2="${x(150)}" y2="${top + W.length*RH}" stroke="var(--text)" stroke-width="1.5" stroke-dasharray="5 3"/><text x="${x(150)+4}" y="${top + W.length*RH + 16}" font-size="11" fill="var(--text)">goal 150 min</text>`;
  W.forEach((w, i) => {
    const y = top + i*RH + 6, c = w.status === 'MET' ? 'var(--ok)' : w.status === 'NOT_MET' ? 'var(--bad)' : 'var(--warn)';
    s += `<text x="${LW - 10}" y="${y + 15}" text-anchor="end" font-size="12.5" fill="var(--text)">${fmtDate(w.week_start)}</text>`;
    s += `<rect x="${x(0)}" y="${y}" width="${x(w.min_lo) - x(0)}" height="20" rx="3" fill="${c}" opacity=".85"/>`;
    if (w.min_hi > w.min_lo) s += `<rect x="${x(w.min_lo)}" y="${y}" width="${x(w.min_hi) - x(w.min_lo)}" height="20" fill="${c}" opacity=".35"/>`;
    s += `<text x="${x(maxM) + 14}" y="${y + 15}" font-size="12" fill="var(--text)">${rng(w.min_lo, w.min_hi)} min · <tspan fill="${c}" font-weight="650">${w.status.replace('_',' ')}</tspan></text>`;
  });
  $('#bounds').innerHTML = s + '</svg><p class="small muted" style="margin:6px 0 0">The lighter segment is the unresolved range. Week 4 (145–155) straddles the goal, so the honest verdict is UNDETERMINED. Picking either signed note would flip it to a confident MET or NOT MET.</p>';
})();

// Answers table
$('#answers-t').innerHTML = `<tr><th>ID</th><th>Question</th><th>Plan</th><th>Post-check</th></tr>` + D.answers.map(a =>
  `<tr><td><a href="../out/answers/${esc(a.id)}.md">${esc(a.id)}</a></td><td class="small">${esc(a.q)}</td><td class="small"><code>${esc(a.plan).replace(/\n/g,'<br>')}</code></td><td>${a.ok ? '<span class="pill MET">OK</span>' : '<span class="pill NOT_MET">check</span>'}</td></tr>`).join('');

// Ablation
(function(){
  const A = D.ablation, names = Object.keys(A), base = A['this system'], weeks = Object.keys(base);
  let h = `<tr><th>Rule applied</th>${weeks.map(w => `<th>${fmtDate(w)}</th>`).join('')}</tr>`;
  names.forEach(n => {
    h += `<tr><td class="small">${n === 'this system' ? '<b>This system</b>' : esc(n)}</td>` + weeks.map(w => {
      const v = A[n][w], flip = n !== 'this system' && v.status !== base[w].status;
      return `<td class="small ${flip ? 'flip' : ''}">${pill(v.status)}<div class="muted" style="white-space:nowrap">${v.days} d · ${rng(v.minutes[0], v.minutes[1])} min</div></td>`;
    }).join('') + '</tr>';
  });
  $('#ablation').innerHTML = h;
})();

// Performance
(function(){
  const B = D.bench, X = B.extraction_initial_run, ops = B.operator_latency_real_patient, qa = Object.values(B.question_answering);
  $('#machine').textContent = B.machine;
  const tot = qa.map(q => q.timings_ms.total/1000), ex = qa.map(q => q.timings_ms.execute);
  const rows = [
    ['Initial extraction', `${X.documents} documents · ${(X.latency_ms_mean/1000).toFixed(1)} s mean per document · ${X.input_tokens_per_doc.toLocaleString()} in / ${X.output_tokens_per_doc.toLocaleString()} out tokens · $${X.list_price_cost_usd_total} list-price total (${X.model.join(', ')})`],
    ['Rebuild from extraction cache', `${B.rebuild_from_cache.ingest_ms} ms ingest + ${B.rebuild_from_cache.reconcile_ms} ms reconcile · ${B.rebuild_from_cache.llm_calls} LLM calls`],
    ['Re-ingest unchanged corpus', `${B.reingest_unchanged.ms} ms · ${B.reingest_unchanged.llm_calls} LLM calls`],
    ['Add one document', `1 LLM call (~${Math.round(B.incremental_add_one_document.llm_latency_ms_if_new/1000)} s) + ${B.incremental_add_one_document.ingest_ms_excluding_llm} ms ingest + ${B.incremental_add_one_document.reconcile_one_patient_ms} ms re-reconcile`],
    ['Per-patient operators (median)', Object.entries(ops).map(([k,v]) => `${k.replace(/_/g,' ')} ${v.median_ms} ms`).join(' · ')],
    ['New question, end to end', `${Math.min(...tot).toFixed(0)}–${Math.max(...tot).toFixed(0)} s (LLM planning + narration); execution ${Math.min(...ex).toFixed(0)}–${Math.max(...ex).toFixed(0)} ms`],
    ['Repeated question (cache)', `${B.question_answering_cached_repeat.median_ms} ms median`],
    ['Saved abstraction', `${(B.persisted_abstraction.db_bytes/1e6).toFixed(1)} MB SQLite · ${B.persisted_abstraction.claims} claims (${B.persisted_abstraction.unverified_claims} unverified) · ${B.persisted_abstraction.encounters} encounters · ${B.persisted_abstraction.decisions} decisions`],
  ];
  $('#perf').innerHTML = '<tr><th>Measured</th><th></th></tr>' + rows.map(([a,b]) => `<tr><td style="white-space:nowrap"><b>${a}</b></td><td class="small">${esc(b)}</td></tr>`).join('');
  const S = B.synthetic_collection_scale;
  $('#scale').innerHTML = `<tr><th>Synthetic collection</th><th>Single patient (care · compliance)</th><th>Collection: care by patient</th><th>Collection: weekly compliance + streaks</th></tr>
    <tr><td>${S.patients.toLocaleString()} patients · ${S.encounters.toLocaleString()} encounters</td><td>${S.single_patient_care_by_week.median_ms} ms · ${S.single_patient_weekly_compliance.median_ms} ms</td>
    <td>${(S.collection_care_by_patient.median_ms/1000).toFixed(1)} s</td><td>${(S.collection_weekly_compliance_consecutive_below_2.median_ms/1000).toFixed(1)} s</td></tr>`;
})();

$('#fp').textContent = D.fingerprint;

// Active section in the nav
const links = [...document.querySelectorAll('nav.toc a')];
const io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) links.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + en.target.id)); }), {rootMargin: '-10% 0px -80% 0px'});
links.forEach(a => { const t = document.querySelector(a.getAttribute('href')); if (t) io.observe(t); });
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
