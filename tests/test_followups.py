"""Follow-ups to the Codex-review fixes: post-check number pool (#44), read-only CLI commands (#45), verify-answers on
an empty directory (#46), dates absent from their document (#52), MRN corrections applied across documents (#53),
free-text and whitespace rosters (#54), printed-MRN fallback (#55) and `stats` reporting (#56).
Hand-built extractions, temp DBs, a monkeypatched extractor; no LLM."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

import backbone.answer as A
from backbone import cli
from backbone import ingest as ingest_mod
from backbone.db import connect
from backbone.ingest import build_claims, ingest
from backbone.query import QueryPlan
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, Observation, ServiceEvent

SESSION = "Individual therapy 2026-01-07 10:00-10:50, completed."


def extraction(line: str, *, name=None, mrn=None, dob=None, eid="X1", date="2026-01-07", observations=()) -> Extraction:
    return Extraction(
        document=DocumentInfo(document_id=None, title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name=name, patient_mrn=mrn, patient_dob=dob, relations=[]),
        service_events=[ServiceEvent(
            encounter_id=eid, related_encounter_id=None, appointment_id=None, service_date=date,
            service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
            disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
            patient_departure=None, patient_contact_intervals=[{"start": "10:00", "end": "10:50"}],
            nontherapeutic_intervals=[], stated_minutes=None, clinicians=[], quotes=[line])],
        assessments=[], observations=list(observations), plan_requirements=[])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp DB + fake extractor returning `by_file[filename]`."""
    by_file: dict = {}
    monkeypatch.setattr(ingest_mod, "extract_document", lambda sha, name, text, **k: (by_file[name], {"from_cache": False}))
    monkeypatch.setattr("backbone.extract.complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    db = tmp_path / "t.db"
    conn = connect(db)

    def run(*files, **kw):
        stats = ingest(conn, list(files), log=lambda *a: None, **kw)
        reconcile_patients(conn, stats["affected_patients"])
        return stats

    return conn, tmp_path, by_file, run, db


def encounter_mrns(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM encounters"))


def patient_mrns(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM patients"))


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- #44 post-check known-number pool

def _pc_db(tmp_path):
    conn = connect(tmp_path / "pc.db")
    conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) VALUES (?,?,?,?,?,?)",
                 ("a" * 64, "T-D1", "[]", "\n".join(f"line {i}" for i in range(1, 13)), "ZZ-1", "2026-01-01T00:00:00"))
    conn.execute("INSERT INTO patients(mrn, name, dob) VALUES ('ZZ-1', 'Alex Doe', NULL)")
    conn.commit()
    return conn


def _results():
    return {"question": "Q?", "plan": {"question": "Q?", "steps": []}, "results": [{
        "op": "care", "params": {"group_by": "none"},
        "totals": {"minutes": {"low": 50, "high": 50}, "sessions": 1},
        "calculation": ["ZZ-E7: 10:00-10:50 (arrival-departure) = 50 min; week 2026-01-05..2026-01-11",
                        "sessions = 1 of 3 scheduled"],
        "facts": [{"encounter_key": "ZZ-1|ZZ-E417", "date": "2026-01-23", "requirement": "ZZ-1|plan|T-D1|sessions|61",
                   "reason": "corrected by T-D1 (claim 3b3f50db40b3:relation:7) on January 27"}],
        "evidence": [{"claim_id": "3b3f50db40b3:service_event:0", "doc_id": "T-D1", "file": "note_88.txt",
                      "record_type": "clinical_note",
                      "passages": [{"lines": "6", "quote": "Session 10:00-10:50, PHQ-9 total 14; 2 breaks"}]}],
        "sql": "SELECT 1"}]}


@pytest.mark.parametrize("n", ["40", "7", "417", "61", "88", "9", "23", "11", "27", "2026", "50.5"])
def test_number_only_inside_ids_dates_or_hex_fails_postcheck(tmp_path, n):
    # 40/7: inside a claim ID (hex, index); 417/61/88/9: an encounter key, a requirement key, a file name, PHQ-9;
    # 23/11/27/2026: dates (ISO, a week range, month-name); 50.5: never stated at all.
    pc = A.postcheck(_pc_db(tmp_path), f"The patient had {n} sessions (T-D1 L6).", _results())
    assert pc["numbers_not_in_results"] == [n] and not pc["ok"], pc


@pytest.mark.parametrize("n", ["50", "1", "3", "14", "2"])
def test_number_stated_in_computed_values_passes_postcheck(tmp_path, n):
    # JSON numbers (50, 1), a calculation's "1 of 3", a quote's "total 14" and "2 breaks".
    pc = A.postcheck(_pc_db(tmp_path), f"Total {n} (T-D1 L6).", _results())
    assert pc["ok"], pc


def test_cached_answer_is_post_checked_again_before_it_is_served(tmp_path, monkeypatch):
    # A cache row written under a looser post-check must not be served as good once the check rejects it.
    conn = _pc_db(tmp_path)
    q = "How many?"
    key = hashlib.sha256((q + A.fingerprint(conn)).encode()).hexdigest()
    stale = {"answer_markdown": "Total 417 minutes (T-D1 L6).", "results": _results(), "postcheck": {"ok": True},
             "timings_ms": {}}
    conn.execute("INSERT INTO answer_cache VALUES (?,?,?,?)", (key, q, json.dumps(stale), "t"))
    conn.commit()
    called = []
    monkeypatch.setattr(A, "complete_json", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(RuntimeError("llm")))
    with pytest.raises(RuntimeError):
        A.answer_question(q, db_path=tmp_path / "pc.db")
    assert called                      # a miss: the planner was asked


# ---------------------------------------------------------------- #45 read-only commands leave the DB untouched

def _saved(tmp_path, monkeypatch):
    conn = _pc_db(tmp_path)
    conn.close()
    db = tmp_path / "pc.db"
    ans, res = tmp_path / "a.md", tmp_path / "r.json"
    ans.write_text("Total 50 minutes (T-D1 L6).")
    res.write_text(json.dumps(_results()))
    return db, ans, res


@pytest.mark.parametrize("argv", [["directory"], ["stats"], ["postcheck", "{ans}", "--results", "{res}"],
                                  ["export", "--patient", "ZZ-1"]])
def test_read_only_commands_leave_db_byte_identical(tmp_path, monkeypatch, capsys, argv):
    db, ans, res = _saved(tmp_path, monkeypatch)
    monkeypatch.setattr("backbone.export.OUT", tmp_path / "exports")
    before = _sha(db)
    argv = [a.format(ans=ans, res=res) for a in argv]
    try:
        cli.main(["--db", str(db), *argv])
    except SystemExit as e:
        assert e.code in (0, None)
    assert _sha(db) == before


def _old_db(tmp_path):
    """A DB from before quarantine / identifier_changes / pending_reconcile (and the week view) existed."""
    db = tmp_path / "old.db"
    conn = _pc_db(tmp_path)
    conn.close()
    (tmp_path / "pc.db").rename(db)
    conn = sqlite3.connect(db)
    conn.executescript("DROP TABLE quarantine; DROP TABLE identifier_changes; DROP TRIGGER trg_pending_cleared_on_reconcile;"
                       "DROP TRIGGER trg_pending_cleared_on_patient_delete; DROP TABLE pending_reconcile;"
                       "DROP VIEW v_encounter_week;")
    conn.close()
    return db


def test_read_only_commands_tolerate_an_older_db(tmp_path, capsys):
    db = _old_db(tmp_path)
    before = _sha(db)
    cli.main(["--db", str(db), "stats"])
    out = json.loads(capsys.readouterr().out)
    assert out["quarantined_documents"] == {} and out["pending_reconcile"]["patients"] == 0
    cli.main(["--db", str(db), "directory"])
    from backbone.db import connect_readonly
    assert connect_readonly(db).execute("SELECT COUNT(*) FROM v_encounter_week").fetchone()[0] == 0
    assert _sha(db) == before


# ---------------------------------------------------------------- #46 verify-answers with nothing to verify

@pytest.mark.parametrize("make", [False, True])
def test_verify_answers_with_no_saved_answers_exits_1(tmp_path, monkeypatch, capsys, make):
    out = tmp_path / "answers"
    if make:
        out.mkdir()
        (out / "notes.json").write_text("{}")          # a JSON file without a plan is not a saved answer
    monkeypatch.setattr(A, "OUT_DIR", out)
    _pc_db(tmp_path).close()
    with pytest.raises(SystemExit) as e:
        cli.main(["--db", str(tmp_path / "pc.db"), "verify-answers"])
    assert e.value.code == 1
    assert "no saved answers" in capsys.readouterr().err


# ---------------------------------------------------------------- #52 a date absent from the whole document

OBS_TEXT = "Patient: Alex Doe | MRN ZZ-1\n" + SESSION + "\nThey said they slept poorly the night before.\n"


def _obs(date):
    return Observation(date=date, domain="sleep", source="patient_report", statement="Slept poorly.",
                       quote="They said they slept poorly the night before.")


def test_observation_dated_with_a_date_absent_from_document_is_not_dated_evidence(env):
    conn, tmp, by_file, run, db = env
    f = tmp / "note.txt"
    f.write_text(OBS_TEXT)
    # 2026-01-07 is in the document (the session line); 2026-01-06 is inferred and stated nowhere.
    by_file["note.txt"] = extraction(SESSION, mrn="ZZ-1", observations=[_obs("2026-01-07"), _obs("2026-01-06")])
    run(f)
    rows = {json.loads(r["payload"])["date"]: r["verified"]
            for r in conn.execute("SELECT payload, verified FROM claims WHERE kind='observation'")}
    assert rows == {"2026-01-07": 1, "2026-01-06": 0}
    assert [r[0] for r in conn.execute("SELECT obs_date FROM observations")] == ["2026-01-07"]
    assert conn.execute("SELECT COUNT(*) FROM decisions WHERE rule='R0'").fetchone()[0] == 1


def test_absent_date_on_build_claims_is_unverified_but_header_date_is_not():
    ex = extraction(SESSION, mrn="ZZ-1", observations=[_obs("2026-01-07"), _obs("2026-01-06")])
    obs = [c for c in build_claims("f" * 64, "T", OBS_TEXT, ex, "ZZ-1") if c["kind"] == "observation"]
    assert [c["verified"] for c in obs] == [1, 0]
    assert json.loads(obs[1]["evidence"])[-1]["grounding"] == {"date": "absent"}


# ---------------------------------------------------------------- #53 an MRN correction applies to every document

def _correction_docs(tmp, by_file):
    a, b = tmp / "a.txt", tmp / "b.txt"
    line_b = "Individual therapy 2026-01-08 10:00-10:50, completed."
    a.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    b.write_text(f"Patient: Alex Doe\nIdentifier note: MRN ZZ-1 corrected to MRN ZZ-2.\n{line_b}\n")
    by_file["a.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    by_file["b.txt"] = extraction(line_b, name="Alex Doe", mrn="ZZ-2", eid="X2", date="2026-01-08")
    return a, b


@pytest.mark.parametrize("order", ["separate", "same_batch"])
def test_mrn_correction_moves_other_documents_with_the_old_mrn(env, order):
    conn, tmp, by_file, run, db = env
    a, b = _correction_docs(tmp, by_file)
    if order == "separate":
        run(a)
        assert encounter_mrns(conn) == ["ZZ-1"]
        s = run(b)
        assert s["affected_patients"] == ["ZZ-1", "ZZ-2"]
        assert [(r["doc_label"], r["from"], r["to"]) for r in s["reattributed"]] == [("a", "ZZ-1", "ZZ-2")]
    else:
        run(a, b)
    assert encounter_mrns(conn) == ["ZZ-2", "ZZ-2"]
    assert patient_mrns(conn) == ["ZZ-2"]
    assert {r[0] for r in conn.execute("SELECT patient_mrn FROM documents")} == {"ZZ-2"}


def test_mrn_correction_chain_is_followed(env):
    conn, tmp, by_file, run, db = env
    a, b = _correction_docs(tmp, by_file)
    c = tmp / "c.txt"
    line_c = "Individual therapy 2026-01-09 10:00-10:50, completed."
    c.write_text(f"Patient: Alex Doe\nMRN ZZ-2 changed to ZZ-3 after a registration merge.\n{line_c}\n")
    by_file["c.txt"] = extraction(line_c, name="Alex Doe", mrn="ZZ-3", eid="X3", date="2026-01-09")
    run(a)
    run(b)
    run(c)
    assert encounter_mrns(conn) == ["ZZ-3"] * 3 and patient_mrns(conn) == ["ZZ-3"]


def test_mrn_correction_cycle_or_fork_is_quarantined_not_guessed(env):
    conn, tmp, by_file, run, db = env
    a, b = _correction_docs(tmp, by_file)
    c = tmp / "c.txt"
    line_c = "Individual therapy 2026-01-09 10:00-10:50, completed."
    c.write_text(f"Patient: Alex Doe\nMRN ZZ-1 corrected to MRN ZZ-9.\n{line_c}\n")      # a fork: ZZ-1 -> ZZ-2 | ZZ-9
    by_file["c.txt"] = extraction(line_c, name="Alex Doe", mrn="ZZ-9", eid="X3", date="2026-01-09")
    run(a, b)
    s = run(c)
    q = {r["doc_label"]: (r["status"], json.loads(r["candidates"])) for r in conn.execute("SELECT * FROM quarantine")}
    assert q["a"] == ("ambiguous_patient", ["ZZ-2", "ZZ-9"])
    # The documents stating the corrections keep their own (explicit) new MRN.
    assert "b" not in q and "c" not in q
    assert encounter_mrns(conn) == ["ZZ-2", "ZZ-9"]
    # A cycle (ZZ-2 -> ZZ-1 on top of ZZ-1 -> ZZ-2) resolves nothing either.
    d = tmp / "d.txt"
    line_d = "Individual therapy 2026-01-10 10:00-10:50, completed."
    d.write_text(f"Patient: Alex Doe\nMRN ZZ-2 corrected to MRN ZZ-1.\n{line_d}\n")
    by_file["d.txt"] = extraction(line_d, name="Alex Doe", mrn="ZZ-1", eid="X4", date="2026-01-10")
    run(d)       # terminates (no oscillation)
    # Deliberate cascade: ZZ-2 now leads back into the ZZ-1 fork, so b (resolving to ZZ-2) and d (to ZZ-1) are
    # quarantined with a; only c (ZZ-9, no outgoing correction) stays attributed. A document stating a correction can
    # itself be quarantined by a later, conflicting one.
    q = {r["doc_label"]: r["status"] for r in conn.execute("SELECT * FROM quarantine")}
    assert q == {"a": "ambiguous_patient", "b": "ambiguous_patient", "d": "ambiguous_patient"}
    assert encounter_mrns(conn) == ["ZZ-9"] and patient_mrns(conn) == ["ZZ-9"]


# ---------------------------------------------------------------- #54 free-text attendee lists, whitespace tables

@pytest.mark.parametrize("lines", [
    "Attendees: Alex Doe, Sam Roe\n",
    "Group members present: Alex Doe; Sam Roe and Kim Poe\n",
    "Name         MRN      Status\nAlex Doe     ZZ-1     Attended\nSam Roe      ZZ-2     Attended\n",
    "Patient name     Arrived   Departed\nAlex Doe         10:00     10:50\nSam Roe          10:05     10:50\n",
])
def test_free_text_and_whitespace_rosters_are_quarantined(env, lines):
    conn, tmp, by_file, run, db = env
    f = tmp / "group.txt"
    f.write_text(f"Group therapy note\n{lines}{SESSION}\n")
    by_file["group.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert [q["status"] for q in s["quarantined"]] == ["multi_patient"]
    assert encounter_mrns(conn) == []


@pytest.mark.parametrize("lines", [
    "Participants: Alex Doe and Casey Doe; both present for the full session\n",   # family members, not patients
    "Attendees: Alex Doe, Casey Doe (partner), Mira Patel, LCSW\n",               # annotated non-patients
    "Patient      Alex Doe\nClinician    Mira Patel\nDate         2026-01-07\n",  # aligned key/value block
])
def test_family_staff_and_key_value_blocks_are_not_rosters(env, lines):
    conn, tmp, by_file, run, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{lines}{SESSION}\n")
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert s["quarantined"] == [] and encounter_mrns(conn) == ["ZZ-1"]


# ---------------------------------------------------------------- #55 a printed MRN when the extraction missed it

def test_printed_mrn_is_used_when_extraction_has_none(env):
    conn, tmp, by_file, run, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe")          # extractor missed the MRN
    s = run(f)
    assert s["quarantined"] == [] and encounter_mrns(conn) == ["ZZ-1"]
    assert conn.execute("SELECT name FROM patients WHERE mrn='ZZ-1'").fetchone()[0] == "Alex Doe"
    a = conn.execute("SELECT basis, reason FROM attribution_notes").fetchall()
    assert [r["basis"] for r in a] == ["printed_mrn"] and "not the extraction" in a[0]["reason"]


def test_printed_mrn_of_a_differently_named_patient_is_quarantined(env):
    conn, tmp, by_file, run, db = env
    p1, f = tmp / "p1.txt", tmp / "note.txt"
    p1.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    by_file["p1.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    line = "Individual therapy 2026-01-08 10:00-10:50, completed."
    f.write_text(f"Patient: Blair Roe | MRN ZZ-1\n{line}\n")
    by_file["note.txt"] = extraction(line, name="Blair Roe", eid="X2", date="2026-01-08")     # MRN missed
    run(p1)
    s = run(f)
    assert [(q["status"], q["candidates"]) for q in s["quarantined"]] == [("mrn_mismatch", ["ZZ-1"])]
    assert encounter_mrns(conn) == ["ZZ-1"]


def test_printed_mrn_fallback_needs_exactly_one_mrn(env):
    conn, tmp, by_file, run, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe\n{SESSION}\n")
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe")
    s = run(f)
    assert [q["status"] for q in s["quarantined"]] == ["no_patient_identity"]


# ---------------------------------------------------------------- #56 stats reports grounding and pending reconciles

def test_stats_reports_grounding_flags_and_pending_reconciles(env, capsys):
    conn, tmp, by_file, run, db = env
    f = tmp / "note.txt"
    f.write_text(OBS_TEXT)
    by_file["note.txt"] = extraction(SESSION, mrn="ZZ-1", observations=[_obs("2026-01-06")])
    ingest(conn, [f], log=lambda *a: None)                     # not reconciled: ZZ-1 stays pending
    cli.main(["--db", str(db), "stats"])
    out = json.loads(capsys.readouterr().out)
    assert out["grounding"]["date"] == {"quote": 1, "document": 0, "absent": 1}
    assert out["grounding"]["time"]["quote"] == 2
    assert out["pending_reconcile"]["patients"] == 1 and out["pending_reconcile"]["oldest_marked_at"]


def test_month_day_lists_are_dates_but_quantities_after_them_are_checked(tmp_path):
    # "Jan 8, 15 and 27" names dates; in "Jan 5–18, 2.0 wk" the 2.0 is a quantity that must still be backed.
    res = _results()
    res["results"][0]["totals"]["weeks"] = 2.0
    conn = _pc_db(tmp_path)
    assert A.postcheck(conn, "Calls on Jan 8, 15 and 27 (T-D1 L6).", res)["ok"]
    assert A.postcheck(conn, "Before (Jan 5–18, 2.0 wk) (T-D1 L6).", res)["ok"]
    assert A.postcheck(conn, "Before (Jan 5–18, 3.5 wk) (T-D1 L6).", res)["numbers_not_in_results"] == ["3.5"]
    assert A.postcheck(conn, "On Jan 8, 40 minutes (T-D1 L6).", res)["numbers_not_in_results"] == ["40"]
    # A year-less m/d in an answer may be a ratio: it stays checked.
    assert A.postcheck(conn, "Attended 4/5 sessions (T-D1 L6).", res)["numbers_not_in_results"] == ["4", "5"]
    assert A.postcheck(conn, "On 1/7/2026, 1 session (T-D1 L6).", res)["ok"]


# ---------------------------------------------------------------- #59 same-label documents in the post-check

SHA_A, SHA_B = "a" * 64, "b" * 64


def _shared_label_db(tmp_path):
    conn = connect(tmp_path / "s.db")
    for sha in (SHA_A, SHA_B):
        conn.execute("INSERT INTO documents(sha256, doc_label, paths, text, patient_mrn, ingested_at) VALUES "
                     "(?,?,?,?,?,?)", (sha, "NOTE", "[]", "x", "ZZ-1", "t"))
    conn.commit()
    return conn


def _shared_results():
    return {"results": [{"op": "care", "totals": {"minutes": {"low": 50, "high": 50}}, "evidence": [
        {"claim_id": "x", "doc_id": "NOTE", "doc_sha": SHA_A[:12], "file": "a.txt", "record_type": "clinical_note",
         "passages": [{"lines": "3", "quote": "q"}]},
        {"claim_id": "y", "doc_id": "NOTE", "doc_sha": SHA_B[:12], "file": "b.txt", "record_type": "clinical_note",
         "passages": [{"lines": "9", "quote": "q"}]}]}]}


def test_line_in_one_same_label_document_does_not_back_the_other(tmp_path):
    conn, res = _shared_label_db(tmp_path), _shared_results()
    assert A.postcheck(conn, f"50 minutes (NOTE [{SHA_A[:12]}] L3; NOTE [{SHA_B[:12]}] L9).", res)["ok"]
    pc = A.postcheck(conn, f"50 minutes (NOTE [{SHA_B[:12]}] L3).", res)
    assert pc["line_refs_outside_evidence"] == [f"NOTE [{SHA_B[:12]}] L3"] and not pc["ok"]


def test_shared_label_cited_without_sha_is_ambiguous(tmp_path):
    pc = A.postcheck(_shared_label_db(tmp_path), "50 minutes (NOTE L9).", _shared_results())
    assert pc["ambiguous_citations"] == ["NOTE"] and not pc["ok"]


def test_citation_with_unknown_sha_is_an_unknown_document(tmp_path):
    pc = A.postcheck(_shared_label_db(tmp_path), "50 minutes (NOTE [cccccccccccc] L9).", _shared_results())
    assert pc["unknown_documents"] == ["NOTE [cccccccccccc]"] and not pc["ok"]


def test_sha_in_citation_is_not_read_as_a_number(tmp_path):
    conn = _shared_label_db(tmp_path)
    conn.execute("UPDATE documents SET sha256='123456789012' || substr(sha256, 13) WHERE sha256=?", (SHA_B,))
    res = _shared_results()
    res["results"][0]["evidence"][1]["doc_sha"] = "123456789012"
    pc = A.postcheck(conn, "50 minutes (NOTE [123456789012] L9).", res)
    assert pc["ok"], pc


# ---------------------------------------------------------------- #57 indexes for the shared-label and R0 lookups

def test_shared_label_and_r0_lookups_use_indexes(tmp_path):
    conn = connect(tmp_path / "i.db")
    # The statements operators.py runs (`_shared_labels`, and `_rejections` for patients="all" and a batch of MRNs).
    r0 = ("SELECT d.mrn, d.reason, c.claim_id, c.kind, c.doc_label, c.sha256, c.payload FROM decisions d "
          "JOIN claims c ON c.claim_id = json_extract(d.claim_ids, '$[0]') WHERE d.rule = 'R0'")
    plans = {
        "label": "SELECT doc_label FROM documents GROUP BY doc_label HAVING COUNT(*) > 1",
        "r0": r0 + " AND d.mrn IN ('ZZ-1','ZZ-2') ORDER BY d.mrn, c.claim_id",
        "r0_all": r0 + " ORDER BY d.mrn, c.claim_id",
    }
    detail = {k: " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + q)) for k, q in plans.items()}
    assert "ix_documents_label" in detail["label"], detail
    assert "ix_decisions_rule" in detail["r0"] and "ix_decisions_rule" in detail["r0_all"], detail


# ---------------------------------------------------------------- #53 provenance and idempotence

def test_mrn_correction_records_its_basis_and_is_stable_on_reingest(env):
    conn, tmp, by_file, run, db = env
    a, b = _correction_docs(tmp, by_file)
    run(a)
    run(b)
    notes = conn.execute("SELECT d.doc_label, n.mrn, n.basis, n.reason FROM attribution_notes n "
                         "JOIN documents d USING (sha256)").fetchall()
    assert [(r[0], r[1], r[2]) for r in notes] == [("a", "ZZ-2", "identifier_change")]
    assert "ZZ-1 corrected to ZZ-2 by b L2" in notes[0][3]
    s = run(a, b)                                    # nothing new: no re-attribution, nobody pending
    assert s["reattributed"] == [] and s["affected_patients"] == []
