"""Answer pipeline and CLI: cache fingerprint (#4), read-only verify-answers (#26), output-path containment (#27),
post-check gate with one regeneration (#35), and the post-check's known-number pool (#37).

No LLM is called: `backbone.answer.complete_json` is stubbed wherever the planner or narrator would run, and the
fingerprint tests ingest from the committed extraction cache.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import pytest

import backbone.answer as A
import backbone.export as X
from backbone import cli
from backbone.db import ROOT, connect
from backbone.extract import CACHE_DIR, extract_document
from backbone.ingest import ingest
from backbone.llm import LLMResult
from backbone.query import CareStep, ComplianceStep, QueryPlan, Scope
from backbone.reconcile import reconcile_patients

DOC_TEXT = "\n".join(f"line {i}" for i in range(1, 13))


def _db(tmp_path, name="a.db"):
    conn = connect(tmp_path / name)
    conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) VALUES (?,?,?,?,?,?)",
                 ("a" * 64, "T-D1", "[]", DOC_TEXT, "ZZ-1", "2026-01-01T00:00:00"))
    conn.commit()
    return conn


def _results(passages=("6", "7", "9"), params=None):
    """A canned results envelope (decoupled from operator output). The asker's question lives in `question`/`plan`."""
    return {"question": "Q?", "plan": {"question": "Q?", "steps": []}, "results": [{
        "op": "care", "params": params or {"group_by": "none"},
        "totals": {"minutes": {"low": 50, "high": 50}, "sessions": 1},
        "calculation": ["ZZ-E7: 10:00-10:50 = 50 min"],
        "evidence": [{"claim_id": "x", "doc_id": "T-D1", "file": "t.txt", "record_type": "clinical_note",
                      "passages": [{"lines": p, "quote": f"line {p}"} for p in passages]}],
        "sql": "SELECT 1"}]}


def _no_llm(*a, **k):
    raise AssertionError("LLM must not be called")


# ---------------------------------------------------------------- #37 numbers that only the plan supplied

def test_postcheck_rejects_number_only_in_step_params(tmp_path):
    res = _results(params={"scope": {"patients": ["ZZ-1"]}, "consecutive_below": 4321})
    pc = A.postcheck(_db(tmp_path), "Below goal for 4321 consecutive weeks (T-D1 L6).", res)
    assert pc["numbers_not_in_results"] == ["4321"] and not pc["ok"], pc


def test_postcheck_accepts_parameter_value_the_operator_also_states(tmp_path):
    res = _results(params={"consecutive_below": 4321})
    res["results"][0]["facts"] = [{"run_threshold_weeks": 4321}]
    assert A.postcheck(_db(tmp_path), "Runs of 4321 weeks (T-D1 L6).", res)["ok"]


# ---------------------------------------------------------------- #35 post-check gate

def _stub_llm(monkeypatch, narrations: list[str]):
    """Planner returns a one-step plan; the narrator returns `narrations` in order. Records every call."""
    calls = {"planner": [], "narrator": []}
    plan = QueryPlan(question="", steps=[CareStep(scope=Scope(patients=["ZZ-1"], start=date(2026, 1, 5),
                                                                 end=date(2026, 1, 30)))])
    todo = list(narrations)

    def fake(system, prompt, model_cls, **kw):
        if system == A.PLANNER_SYSTEM:
            calls["planner"].append(prompt)
            return LLMResult(data=plan.model_copy(deep=True), model="stub", latency_ms=0)
        assert system == A.NARRATOR_SYSTEM
        calls["narrator"].append(prompt)
        assert todo, "narrator called more often than expected"
        return LLMResult(data=A.NarrativeOut(answer_markdown=todo.pop(0), unresolved=[], caveats=None),
                         model="stub", latency_ms=0)

    monkeypatch.setattr(A, "complete_json", fake)
    monkeypatch.setattr(A, "execute_plan", lambda conn, plan: _results())
    return calls


GAPPED = "Total 50 minutes (T-D1 L6–9)."          # L8 was never in the evidence
FIXED = "Total 50 minutes (T-D1 L6–7, L9)."


def test_postcheck_accepts_split_citation_of_listed_lines(tmp_path):
    conn = _db(tmp_path)
    assert A.postcheck(conn, FIXED, _results())["ok"]
    assert A.postcheck(conn, GAPPED, _results())["line_refs_outside_evidence"] == ["T-D1 L8"]


def test_failed_postcheck_regenerates_once_with_failures_fed_back(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    calls = _stub_llm(monkeypatch, [GAPPED, FIXED])
    res = A.answer_question("How many minutes?", db_path=tmp_path / "a.db")
    assert len(calls["narrator"]) == 2 and len(calls["planner"]) == 1
    assert "T-D1 L8" in calls["narrator"][1] and GAPPED in calls["narrator"][1]
    assert res["postcheck"]["ok"] and res["answer_markdown"] == FIXED
    assert res["postcheck_attempts"] == 2 and res["llm"]["calls"] == 3
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 1


def test_answer_still_failing_after_retry_is_flagged_and_not_cached(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    calls = _stub_llm(monkeypatch, [GAPPED, GAPPED, GAPPED, GAPPED])
    res = A.answer_question("How many minutes?", db_path=tmp_path / "a.db")
    assert len(calls["narrator"]) == 2
    assert not res["postcheck"]["ok"] and res["postcheck_attempts"] == 2
    assert "Post-check failed" in A.render_markdown(res)
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 0
    again = A.answer_question("How many minutes?", db_path=tmp_path / "a.db")      # not served from the cache
    assert not again["cached"] and len(calls["narrator"]) == 4 and len(calls["planner"]) == 2


def test_passing_first_narration_is_not_regenerated(tmp_path, monkeypatch):
    _db(tmp_path)
    calls = _stub_llm(monkeypatch, [FIXED])
    res = A.answer_question("How many minutes?", db_path=tmp_path / "a.db")
    assert len(calls["narrator"]) == 1 and res["postcheck"]["ok"] and res["postcheck_attempts"] == 1
    hit = A.answer_question("How many minutes?", db_path=tmp_path / "a.db")
    assert hit["cached"] and len(calls["narrator"]) == 1


def test_cached_answer_that_failed_postcheck_is_a_miss(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    q = "How many minutes?"
    key = hashlib.sha256((q + A.fingerprint(conn)).encode()).hexdigest()
    stale = {"answer_markdown": GAPPED, "postcheck": {"ok": False}, "timings_ms": {}}
    conn.execute("INSERT INTO answer_cache VALUES (?,?,?,?)", (key, q, json.dumps(stale), "2026-01-01"))
    conn.commit()
    calls = _stub_llm(monkeypatch, [FIXED])
    res = A.answer_question(q, db_path=tmp_path / "a.db")
    assert not res["cached"] and res["postcheck"]["ok"] and len(calls["narrator"]) == 1


def test_narrator_prompt_forbids_gapped_ranges():
    s = A.NARRATOR_SYSTEM.lower()
    assert "non-adjacent" in s and "listed" in s


# ---------------------------------------------------------------- #26 verify-answers is read-only and strict

def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _saved_answer(tmp_path, monkeypatch, answer_md, *, results=None):
    out = tmp_path / "answers"
    out.mkdir()
    monkeypatch.setattr(A, "OUT_DIR", out)
    canned = _results()
    monkeypatch.setattr(A, "execute_plan", lambda conn, plan: canned)
    res = {"id": "T-01", "question": "Q?", "plan": QueryPlan(question="Q?", steps=[]).model_dump(mode="json"),
           "plan_explain": "", "results": results or canned, "answer_markdown": answer_md, "unresolved": [],
           "caveats": None, "postcheck": {"ok": True}, "timings_ms": {}, "llm": {}}
    # deliberately not in the format verify_answers writes, so any rewrite changes the bytes
    (out / "T-01.json").write_text(json.dumps(res))
    (out / "T-01.md").write_text("# hand-written\n")
    db = tmp_path / "a.db"
    _db(tmp_path).close()
    return out, db


def test_verify_answers_cli_is_read_only_and_fails_on_postcheck(tmp_path, monkeypatch, capsys):
    out, db = _saved_answer(tmp_path, monkeypatch, "Total 9999 minutes (T-D1 L6).")
    before = {p.name: _sha(p) for p in [*out.iterdir(), db]}
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(db), "verify-answers"])
    assert e.value.code == 1
    assert {p.name: _sha(p) for p in [*out.iterdir(), db]} == before
    assert "postcheck_ok=False" in capsys.readouterr().out


def test_verify_answers_passes_when_identical_and_clean(tmp_path, monkeypatch):
    out, db = _saved_answer(tmp_path, monkeypatch, "Total 50 minutes (T-D1 L6).")
    before = {p.name: _sha(p) for p in [*out.iterdir(), db]}
    cli.main(["--db", str(db), "verify-answers"])           # no SystemExit
    assert {p.name: _sha(p) for p in [*out.iterdir(), db]} == before


def test_verify_answers_fails_when_results_differ(tmp_path, monkeypatch):
    out, db = _saved_answer(tmp_path, monkeypatch, "Total 50 minutes (T-D1 L6).", results=_results(passages=("6",)))
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(db), "verify-answers"])
    assert e.value.code == 1


def test_verify_answers_rewrite_is_explicit(tmp_path, monkeypatch):
    out, db = _saved_answer(tmp_path, monkeypatch, "Total 9999 minutes (T-D1 L6).")
    with pytest.raises(SystemExit):
        cli.main(["--db", str(db), "verify-answers", "--rewrite"])
    saved = json.loads((out / "T-01.json").read_text())
    assert saved["postcheck"]["numbers_not_in_results"] == ["9999"]
    assert "Post-check" in (out / "T-01.md").read_text()


# ---------------------------------------------------------------- #27 output identifiers stay inside their directory

BAD_IDS = ["../escaped", "a/b", "/tmp/abs", "..", ".", "", "x\\y", "a\x00b"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_answer_file_rejects_unsafe_question_ids_before_any_llm_call(tmp_path, monkeypatch, bad):
    out = tmp_path / "out" / "answers"
    monkeypatch.setattr(A, "OUT_DIR", out)
    monkeypatch.setattr(A, "answer_question", _no_llm)
    qf = tmp_path / "q.json"
    qf.write_text(json.dumps([{"id": "OK-01", "question": "a"}, {"id": bad, "question": "b"}]))
    with pytest.raises(ValueError):
        A.answer_file(str(qf))
    assert not (tmp_path / "escaped.json").exists() and not (tmp_path / "out" / "escaped.json").exists()


def test_answer_file_rejects_missing_and_duplicate_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "OUT_DIR", tmp_path / "answers")
    monkeypatch.setattr(A, "answer_question", _no_llm)
    for qs in ([{"question": "a"}], [{"id": "Q-1", "question": "a"}, {"id": "Q-1", "question": "b"}]):
        qf = tmp_path / "q.json"
        qf.write_text(json.dumps(qs))
        with pytest.raises(ValueError):
            A.answer_file(str(qf))


def test_answer_file_writes_safe_ids(tmp_path, monkeypatch):
    out = tmp_path / "answers"
    monkeypatch.setattr(A, "OUT_DIR", out)
    fake = {"question": "a", "answer_markdown": "x", "unresolved": [], "plan_explain": "", "results": {"results": []},
            "postcheck": {"numbers_not_in_results": [], "unknown_documents": [], "line_refs_outside_evidence": [],
                          "ok": True}, "timings_ms": {}, "llm": {}, "cached": True}
    monkeypatch.setattr(A, "answer_question", lambda *a, **k: dict(fake))
    qf = tmp_path / "q.json"
    qf.write_text(json.dumps([{"id": "DEV-01", "question": "a"}, {"id": "HG-M042_v1.2", "question": "a"}]))
    A.answer_file(str(qf))
    assert (out / "DEV-01.json").exists() and (out / "HG-M042_v1.2.md").exists()


@pytest.mark.parametrize("bad", ["../evil", "<abs>/evil", "a/b", ".."])
def test_export_rejects_unsafe_mrn(tmp_path, monkeypatch, bad):
    bad = bad.replace("<abs>", str(tmp_path))          # an absolute path, but inside tmp_path if it escapes
    monkeypatch.setattr(X, "OUT", tmp_path / "out" / "abstraction")
    conn = connect(tmp_path / "x.db")
    conn.execute("INSERT INTO patients(mrn, name) VALUES (?,?)", (bad, "Evil"))
    with pytest.raises(ValueError):
        X.export_patient(conn, bad)
    assert not (tmp_path / "out" / "evil.json").exists() and not (tmp_path / "evil.json").exists()


def test_safe_output_path_accepts_real_identifiers(tmp_path):
    from backbone.paths import safe_output_path
    assert safe_output_path(tmp_path, "HG-M042", ".graph.json") == tmp_path / "HG-M042.graph.json"
    assert safe_output_path(tmp_path, "DEV-01", ".json") == tmp_path / "DEV-01.json"


# ---------------------------------------------------------------- #4 the fingerprint follows the abstraction

needs_cache = pytest.mark.skipif(not any(CACHE_DIR.glob("*.json")), reason="extraction cache not built")


def _build(tmp_path, monkeypatch, fail_on=None):
    """Ingest the corpus from the committed extraction cache (no LLM); optionally fail one document's extraction."""
    monkeypatch.setattr("backbone.extract.complete_json", _no_llm)
    state = {"failed": False}

    def flaky(sha, filename, text, **kw):
        if filename == fail_on and not state["failed"]:
            state["failed"] = True
            raise RuntimeError("simulated extraction failure")
        kw.pop("model", None)            # always read the committed cache, whatever model ingest records
        return extract_document(sha, filename, text, **kw)

    monkeypatch.setattr("backbone.ingest.extract_document", flaky)
    conn = connect(tmp_path / "fp.db")
    return conn


def _ingest(conn, **kw):
    st = ingest(conn, [ROOT / "documents"], log=lambda *a: None, **kw)
    reconcile_patients(conn, st["affected_patients"])
    return st


@needs_cache
def test_fingerprint_changes_when_a_failed_extraction_is_retried(tmp_path, monkeypatch):
    victim = sorted((ROOT / "documents").glob("*.txt"))[0].name
    conn = _build(tmp_path, monkeypatch, fail_on=victim)
    st = _ingest(conn)
    assert len(st["failed"]) == 1
    fp_partial = A.fingerprint(conn)            # an answer cached now was computed without that document
    st = _ingest(conn)                          # the retry succeeds; same document hashes as before
    assert not st["failed"] and st["extracted_cache"] == 1
    assert A.fingerprint(conn) != fp_partial


@needs_cache
def test_fingerprint_changes_with_extraction_model(tmp_path, monkeypatch):
    conn = _build(tmp_path, monkeypatch)
    _ingest(conn)
    fp = A.fingerprint(conn)
    _ingest(conn, model="other-model")          # re-extract every document under another model id
    assert A.fingerprint(conn) != fp


@needs_cache
def test_fingerprint_is_stable_across_identical_rebuilds(tmp_path, monkeypatch):
    conn = _build(tmp_path, monkeypatch)
    _ingest(conn)
    fp = A.fingerprint(conn)
    _ingest(conn)                                               # nothing new
    mrns = [r[0] for r in conn.execute("SELECT mrn FROM patients")]
    reconcile_patients(conn, mrns)                              # rebuild the clinical layer: new rowids, timestamps
    assert A.fingerprint(conn) == fp
    conn.execute("UPDATE encounters SET minutes_high = minutes_high + 1 "
                 "WHERE encounter_key = (SELECT MIN(encounter_key) FROM encounters WHERE minutes_high IS NOT NULL)")
    assert A.fingerprint(conn) != fp                            # a derived-table change is visible


def test_fingerprint_tolerates_missing_optional_tables(tmp_path):
    conn = _db(tmp_path)
    conn.execute("DROP TABLE quarantine")
    assert len(A.fingerprint(conn)) == 64
