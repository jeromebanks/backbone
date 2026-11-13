"""Ingest robustness: crash recovery (#3), value grounding (#36), re-attribution of quarantined documents (#41),
roster / MRN-correction guards (#42) and extracted-vs-printed MRN consistency (#43).
Hand-built extractions, temp DBs, a monkeypatched extractor; no LLM. The corpus checks replay the extraction cache."""
from __future__ import annotations

import json

import pytest

from backbone import cli
from backbone import ingest as ingest_mod
from backbone.db import ROOT, connect
from backbone.evidence import ground_values, minutes_in, times_in
from backbone.extract import CACHE_DIR
from backbone.ingest import attribute, build_claims, discover, ingest
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, ServiceEvent

SESSION = "Individual therapy 2026-01-07 10:00-10:50, completed."
DERIVED = ("encounters", "encounter_intervals", "plan_requirements", "assessments", "observations")


def extraction(line: str, *, name=None, mrn=None, dob=None, eid="X1", date="2026-01-07", contact=("10:00", "10:50"),
               arrival=None, departure=None, stated=None) -> Extraction:
    return Extraction(
        document=DocumentInfo(document_id=None, title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name=name, patient_mrn=mrn, patient_dob=dob, relations=[]),
        service_events=[ServiceEvent(
            encounter_id=eid, related_encounter_id=None, appointment_id=None, service_date=date,
            service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
            disposition="attended", patient_present="yes", scheduled=None, patient_arrival=arrival,
            patient_departure=departure, patient_contact_intervals=[{"start": contact[0], "end": contact[1]}],
            nontherapeutic_intervals=[], stated_minutes=stated, clinicians=[], quotes=[line])],
        assessments=[], observations=[], plan_requirements=[])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp DB + fake extractor returning `by_file[filename]`; `calls` records every extraction request."""
    by_file: dict = {}
    calls: list[str] = []

    def fake_extract(sha, name, text, **k):
        calls.append(name)
        return by_file[name], {"from_cache": False}

    monkeypatch.setattr(ingest_mod, "extract_document", fake_extract)
    monkeypatch.setattr("backbone.extract.complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    db = tmp_path / "t.db"
    conn = connect(db)

    def run(*files, **kw):
        stats = ingest(conn, list(files), log=lambda *a: None, **kw)
        reconcile_patients(conn, stats["affected_patients"])
        return stats

    return conn, tmp_path, by_file, run, calls, db


def derived_dump(conn) -> dict:
    """Every derived row, minus timestamps and autoincrement ids."""
    out = {t: sorted(json.dumps(dict(r), sort_keys=True) for r in conn.execute(f"SELECT * FROM {t}")) for t in DERIVED}
    out["decisions"] = sorted(json.dumps({k: r[k] for k in r.keys() if k != "decision_id"}, sort_keys=True)
                              for r in conn.execute("SELECT * FROM decisions"))
    out["conflicts"] = sorted(json.dumps({k: r[k] for k in r.keys() if k != "conflict_id"}, sort_keys=True)
                              for r in conn.execute("SELECT * FROM conflicts"))
    out["patients"] = sorted(json.dumps([r["mrn"], r["name"], r["dob"], r["ruleset_version"]])
                             for r in conn.execute("SELECT * FROM patients"))
    return out


def encounter_mrns(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM encounters"))


def pending(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM pending_reconcile"))


# ---------------------------------------------------------------- #3: a crash before reconcile must not stick

def _two_docs(tmp, by_file):
    a, b = tmp / "a.txt", tmp / "b.txt"
    line_b = "Individual therapy 2026-01-08 10:00-10:50, completed."
    a.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    b.write_text(f"Patient: Blair Roe | MRN ZZ-2\n{line_b}\n")
    by_file["a.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    by_file["b.txt"] = extraction(line_b, name="Blair Roe", mrn="ZZ-2", eid="X2", date="2026-01-08")
    return a, b


def test_crash_between_claims_and_reconcile_is_repaired_by_retry(env, tmp_path, monkeypatch, capsys):
    conn, tmp, by_file, run, calls, db = env
    a, b = _two_docs(tmp, by_file)
    clean = connect(tmp_path / "clean.db")
    reconcile_patients(clean, ingest(clean, [a, b], log=lambda *x: None)["affected_patients"])

    import backbone.reconcile as rec
    real = rec.reconcile_patients

    def crash(*args, **kw):
        raise RuntimeError("simulated crash after the claims were committed")
    monkeypatch.setattr(rec, "reconcile_patients", crash)
    with pytest.raises(RuntimeError):
        cli.main(["--db", str(db), "ingest", str(a), str(b)])
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE patient_mrn IS NOT NULL").fetchone()[0] > 0
    assert encounter_mrns(conn) == []                        # the crash left the clinical layer empty
    assert pending(conn) == ["ZZ-1", "ZZ-2"]                 # ... but durably recorded what is owed

    monkeypatch.setattr(rec, "reconcile_patients", real)
    capsys.readouterr()                                      # drop the crashed run's progress log
    cli.main(["--db", str(db), "ingest", str(a), str(b)])    # the retry: both files are already ingested
    out = json.loads(capsys.readouterr().out)
    assert out["new_documents"] == 0 and out["already_ingested"] == 2
    assert out["affected_patients"] == ["ZZ-1", "ZZ-2"]
    assert pending(conn) == []
    assert derived_dump(conn) == derived_dump(clean)


def test_crash_midway_through_reconcile_keeps_only_unfinished_patients_pending(env, monkeypatch):
    conn, tmp, by_file, run, calls, db = env
    a, b = _two_docs(tmp, by_file)
    stats = ingest(conn, [a, b], log=lambda *x: None)
    import backbone.reconcile as rec
    real_persist = rec.persist

    def persist(c, res):
        if res.mrn == "ZZ-2":
            raise RuntimeError("crash while persisting ZZ-2")
        real_persist(c, res)
    monkeypatch.setattr(rec, "persist", persist)
    with pytest.raises(RuntimeError):
        reconcile_patients(conn, stats["affected_patients"])
    assert pending(conn) == ["ZZ-2"]                         # ZZ-1 committed with its marker cleared
    monkeypatch.setattr(rec, "persist", real_persist)
    again = ingest(conn, [a, b], log=lambda *x: None)
    assert again["affected_patients"] == ["ZZ-2"] and again["pending_from_earlier_runs"] == ["ZZ-2"]


def test_reconcile_command_clears_pending(env, capsys):
    conn, tmp, by_file, run, calls, db = env
    a, _ = _two_docs(tmp, by_file)
    ingest(conn, [a], log=lambda *x: None)                  # no reconcile: as if the process died here
    assert pending(conn) == ["ZZ-1"]
    cli.main(["--db", str(db), "reconcile"])
    assert "ZZ-1" in json.loads(capsys.readouterr().out)
    assert pending(conn) == [] and encounter_mrns(conn) == ["ZZ-1"]


def test_pending_marker_for_vanished_patient_is_cleared(env, capsys):
    # A former owner with no patients row any more: reconciling it must still clear its marker.
    conn, tmp, by_file, run, calls, db = env
    conn.execute("INSERT INTO pending_reconcile VALUES ('GONE-1', '2026-01-01T00:00:00')")
    conn.commit()
    cli.main(["--db", str(db), "reconcile"])
    assert pending(conn) == []


# ---------------------------------------------------------------- #36: payload values must be stated in the quotes

TEXT = ("Document ID: T-D1\n"
        "Patient: Alex Doe | MRN ZZ-1\n"
        "Encounter X1 | Service date January 7, 2026\n"
        "Individual therapy 10:00-10:30, completed.\n"
        "Rowan left at 10:45.\n")


def _grounding(rows, kind="service_event") -> dict:
    ev = next(r for r in rows if r["kind"] == kind)
    tail = json.loads(ev["evidence"])[-1]
    assert tail["match"] == "grounding" and tail["line_start"] is None    # never mistaken for a passage
    return tail["grounding"]


def test_exact_quote_with_ungrounded_departure_is_flagged():
    quote = "Individual therapy 10:00-10:30, completed."
    ex = extraction(quote, mrn="ZZ-1", contact=("10:00", "10:30"), departure="11:30")
    rows = build_claims("f" * 64, "T-D1", TEXT, ex, "ZZ-1")
    g = _grounding(rows)
    assert g["patient_departure"] == "absent"                          # 11:30 appears nowhere in the document
    assert g["patient_contact_intervals[0].start"] == g["patient_contact_intervals[0].end"] == "quote"
    assert g["service_date"] == "document"                              # stated in the header, not the quote
    ev = next(r for r in rows if r["kind"] == "service_event")
    # A session time that its own quote does not state fails verification (R0 drops it); a header-only date alone
    # stays a flag (corpus claims carry those; see the measurement in #36).
    assert ev["verified"] == 0


def test_value_stated_elsewhere_in_document_is_document_grounded():
    quote = "Individual therapy 10:00-10:30, completed."
    rows = build_claims("f" * 64, "T-D1", TEXT, extraction(quote, mrn="ZZ-1", contact=("10:00", "10:30"),
                                                           departure="10:45"), "ZZ-1")
    assert _grounding(rows)["patient_departure"] == "document"


def test_located_spans_are_unchanged_by_grounding():
    quote = "Individual therapy 10:00-10:30, completed."
    rows = build_claims("f" * 64, "T-D1", TEXT, extraction(quote, mrn="ZZ-1", contact=("10:00", "10:30")), "ZZ-1")
    ev = next(r for r in rows if r["kind"] == "service_event")
    spans = [s for s in json.loads(ev["evidence"]) if s["line_start"]]
    assert [(s["quote"], s["line_start"], s["match"]) for s in spans] == [(quote, 4, "exact")]


def test_grounding_normalises_formats():
    assert times_in("9:00") == times_in("09:00") == times_in("9:00 am") == times_in("9.00 a.m.") == {540}
    assert times_in("2 pm") == {840} and times_in("13:00–13:20") == {780, 800}
    assert 50 in minutes_in("50 min") and 50 in minutes_in("50 minutes") and 45 in minutes_in("a 45-minute visit")
    assert 5 not in minutes_in("45 minutes")
    for s in ("2026-01-07", "January 7, 2026", "Jan07", "Jan 7", "7 January 2026", "1/7/2026"):
        assert ground_values([("d", "date", "2026-01-07", [s])]) == {"d": True}, s
    assert ground_values([("d", "date", "2026-01-07", ["January 17, 2026"])]) == {"d": False}
    assert ground_values([("t", "number", 3.0, ["at least three therapy days"])]) == {"t": True}


def test_nontherapeutic_interval_may_be_grounded_by_its_own_quote():
    p = {"quotes": ["Session 13:00-13:55."], "nontherapeutic_intervals": [
        {"start": "13:20", "end": "13:30", "kind": "disconnection", "quote": "Disconnected 13:20-13:30."}],
        "patient_contact_intervals": [], "scheduled": None}
    assert all(ground_values(ingest_mod.grounding_fields("service_event", p)).values())


@pytest.mark.skipif(not any(CACHE_DIR.glob("*.json")), reason="extraction cache not built")
def test_corpus_times_and_minutes_are_all_grounded_in_their_quotes(tmp_path, monkeypatch):
    """Measurement turned regression guard: every clock time and stated minute count the corpus extraction holds is
    stated in its own claim's quotes (dates often are not: they come from document headers)."""
    monkeypatch.setattr("backbone.extract.complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    conn = connect(tmp_path / "c.db")
    ingest(conn, [ROOT / "documents"], log=lambda *a: None)
    status: dict[str, int] = {}
    for r in conn.execute("SELECT evidence FROM claims WHERE kind IN ('service_event')"):
        for field, s in json.loads(r["evidence"])[-1]["grounding"].items():
            if field.split(".")[0].split("[")[0] != "service_date":
                status[s] = status.get(s, 0) + 1
    assert set(status) == {"quote"} and status["quote"] > 100


# ---------------------------------------------------------------- #41: quarantined documents get re-attributed

def test_quarantined_name_only_document_is_attributed_when_its_patient_arrives(env):
    conn, tmp, by_file, run, calls, db = env
    name_only, with_mrn = tmp / "name_only.txt", tmp / "with_mrn.txt"
    line = "Individual therapy 2026-01-08 10:00-10:50, completed."
    name_only.write_text(f"Patient: Alex Doe | DOB 1980-01-01\n{line}\n")
    with_mrn.write_text(f"Patient: Alex Doe | DOB 1980-01-01 | MRN ZZ-1\n{SESSION}\n")
    by_file["name_only.txt"] = extraction(line, name="Alex Doe", dob="1980-01-01", eid="X2", date="2026-01-08")
    by_file["with_mrn.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1", dob="1980-01-01")
    s1 = run(name_only)
    assert [q["status"] for q in s1["quarantined"]] == ["no_patient_identity"]
    s2 = run(with_mrn)
    assert calls == ["name_only.txt", "with_mrn.txt"]                 # stored extraction reused: no re-extraction
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-1"]
    assert conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE patient_mrn IS NULL").fetchone()[0] == 0
    assert [r["doc_label"] for r in s2["reattributed"]] == ["name_only"]
    assert s2["reattributed"][0]["to"] == "ZZ-1" and s2["affected_patients"] == ["ZZ-1"]


def test_name_matched_document_is_quarantined_when_a_same_name_patient_appears(env):
    conn, tmp, by_file, run, calls, db = env
    p1, name_only, p2 = tmp / "p1.txt", tmp / "name_only.txt", tmp / "p2.txt"
    line = "Individual therapy 2026-01-08 10:00-10:50, completed."
    p1.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    name_only.write_text(f"Patient: Alex Doe\n{line}\n")
    p2.write_text(f"Patient: Alex Doe | MRN ZZ-2\n{SESSION}\n")
    by_file["p1.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    by_file["name_only.txt"] = extraction(line, name="Alex Doe", eid="X2", date="2026-01-08")
    by_file["p2.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-2")
    run(p1, name_only)
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-1"]
    s = run(p2)
    # The name no longer identifies one patient: ZZ-1 loses the X2 session, which is held back.
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-2"]
    assert s["affected_patients"] == ["ZZ-1", "ZZ-2"]
    q = conn.execute("SELECT status, candidates FROM quarantine").fetchall()
    assert [(r[0], json.loads(r[1])) for r in q] == [("ambiguous_patient", ["ZZ-1", "ZZ-2"])]


def test_unchanged_attribution_is_not_reported_or_reconciled(env):
    conn, tmp, by_file, run, calls, db = env
    a, b = _two_docs(tmp, by_file)
    run(a)
    s = run(b)
    assert s["reattributed"] == [] and s["affected_patients"] == ["ZZ-2"]


# ---------------------------------------------------------------- #42: roster and MRN-correction guards

def test_tabular_roster_with_mrn_column_is_quarantined(env):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "roster.txt"
    line = "Group therapy 2026-01-07 10:00-10:50."
    f.write_text("Group attendance\n"
                 "Name      | MRN  | Status\n"
                 "Alex Doe  | ZZ-1 | Attended\n"
                 "Blair Roe | ZZ-2 | Attended\n"
                 f"{line}\n")
    by_file["roster.txt"] = extraction(line, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert [(q["status"], q["candidates"]) for q in s["quarantined"]] == [("multi_patient", ["ZZ-1", "ZZ-2"])]
    assert encounter_mrns(conn) == []


def test_tabular_roster_listing_names_only_is_quarantined(env):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "roster.txt"
    line = "Group therapy 2026-01-07 10:00-10:50."
    f.write_text("Patient: Alex Doe | MRN ZZ-1\n"
                 "Patient name\tArrived\tDeparted\n"
                 "Alex Doe\t10:00\t10:50\n"
                 "Blair Roe\t10:05\t10:50\n"
                 f"{line}\n")
    by_file["roster.txt"] = extraction(line, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert [q["status"] for q in s["quarantined"]] == ["multi_patient"]
    assert encounter_mrns(conn) == []


def test_single_patient_table_and_banner_are_not_a_roster():
    text = ("Patient: Alex Doe | DOB: 1980-01-01 | MRN: ZZ-1\n"
            "Date       | Encounter | Patient arrived | Patient departed\n"
            "2026-01-06 | X1        | 10:15           | 11:15\n"
            "2026-01-12 | X2        | 10:00           | 11:30\n"
            "Name | MRN\nAlex Doe | ZZ-1\nAlex Doe | ZZ-1\n")
    ident = ingest_mod.text_identity(text)
    assert ident.mrns == {"ZZ-1"} and not ident.roster_names and not ident.corrections


@pytest.mark.parametrize("phrase", [
    "MRN: ZZ-1 corrected to MRN: ZZ-2",
    "MRN ZZ-1 was changed to ZZ-2 after a registration merge",
    "Corrected MRN: ZZ-2 (previously MRN ZZ-1)",
])
def test_mrn_correction_document_is_attributed_to_corrected_mrn(env, phrase):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe\nIdentifier note: {phrase}.\n{SESSION}\n")
    for extracted in ("ZZ-1", "ZZ-2"):              # whichever of the two the extractor reported
        by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn=extracted)
        s = run(f, model=f"m-{extracted}")
        assert s["quarantined"] == [], (phrase, extracted)
        assert encounter_mrns(conn) == ["ZZ-2"], (phrase, extracted)
        rows = conn.execute("SELECT old_mrn, new_mrn, line FROM identifier_changes").fetchall()
        assert [tuple(r) for r in rows] == [("ZZ-1", "ZZ-2", 2)]


def test_correction_does_not_hide_a_second_patient():
    ident = ingest_mod.text_identity("MRN ZZ-1 corrected to MRN ZZ-2\nAlso present: MRN ZZ-3\n")
    assert ident.mrns == {"ZZ-2", "ZZ-3"}


# ---------------------------------------------------------------- #43: extracted MRN vs MRN printed in the text

def test_extracted_mrn_differing_from_printed_mrn_is_quarantined(env):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-7")      # mistyped by the extractor
    s = run(f)
    assert [(q["status"], q["candidates"]) for q in s["quarantined"]] == [("mrn_mismatch", ["ZZ-1", "ZZ-7"])]
    assert encounter_mrns(conn) == [] and s["affected_patients"] == []


def test_extracted_mrn_not_printed_anywhere_is_quarantined(env):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe | chart ZZ-12\n{SESSION}\n")              # ZZ-1 is only a prefix of ZZ-12
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert [q["status"] for q in s["quarantined"]] == ["mrn_mismatch"]


def test_name_match_contradicting_printed_mrn_is_quarantined(env):
    conn, tmp, by_file, run, calls, db = env
    p1, f = tmp / "p1.txt", tmp / "note.txt"
    p1.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    line = "Individual therapy 2026-01-08 10:00-10:50, completed."
    f.write_text(f"Patient: Alex Doe | MRN ZZ-2\n{line}\n")
    by_file["p1.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    by_file["note.txt"] = extraction(line, name="Alex Doe", eid="X2", date="2026-01-08")   # MRN missed
    run(p1)
    s = run(f)
    assert [q["status"] for q in s["quarantined"]] == ["mrn_mismatch"]
    assert encounter_mrns(conn) == ["ZZ-1"]


def test_mrn_formatting_differences_are_tolerated(env):
    conn, tmp, by_file, run, calls, db = env
    f = tmp / "note.txt"
    f.write_text(f"Patient: Alex Doe | MRN: zz–1\n{SESSION}\n")                 # en dash, lower case
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    s = run(f)
    assert s["quarantined"] == [] and encounter_mrns(conn) == ["ZZ-1"]


# ---------------------------------------------------------------- the new guards must not touch the corpus

@pytest.mark.skipif(not any(CACHE_DIR.glob("*.json")), reason="extraction cache not built")
def test_new_guards_attribute_every_corpus_document(tmp_path):
    from backbone.extract import load_cached
    from backbone.ingest import sha256_bytes
    conn = connect(tmp_path / "g.db")
    files = discover([ROOT / "documents"])
    assert len(files) == 31
    for f in files:
        text = f.read_text()
        ident = ingest_mod.text_identity(text)
        assert ident.mrns == {"HG-M042"} and not ident.roster_names and not ident.corrections, f.name
        ex = Extraction.model_validate(load_cached(sha256_bytes(f.read_bytes()))["extraction"])
        assert attribute(conn, text, ex) == ("HG-M042", None), f.name


def test_session_time_not_in_its_own_quote_fails_verification():
    # #15/#36: the quote is exact, but the departure the arithmetic would use is not what it states.
    from backbone.ingest import build_claims
    from backbone.schema import DocumentInfo, Extraction, ServiceEvent
    text = "Patient: Alex Doe | MRN ZZ-1\nGroup session 10:00-10:30, attended.\nNext group 10:00-11:30 on Friday.\n"
    def ex(dep):
        return Extraction(
            document=DocumentInfo(document_id=None, title="t", signed=True, signed_at=None, received_at=None,
                                  finality="final", patient_name="Alex Doe", patient_mrn="ZZ-1", patient_dob=None,
                                  relations=[]),
            service_events=[ServiceEvent(
                encounter_id="X1", related_encounter_id=None, appointment_id=None, service_date="2026-01-07",
                service_type="group_therapy", modality="in_person", evidence_type="clinical_note",
                disposition="attended", patient_present="yes", scheduled=None, patient_arrival="10:00",
                patient_departure=dep, patient_contact_intervals=[], nontherapeutic_intervals=[],
                stated_minutes=None, clinicians=[], quotes=["Group session 10:00-10:30, attended."])],
            assessments=[], observations=[], plan_requirements=[])
    ok = next(c for c in build_claims("a" * 64, "T", text, ex("10:30"), "ZZ-1") if c["kind"] == "service_event")
    bad = next(c for c in build_claims("a" * 64, "T", text, ex("11:30"), "ZZ-1") if c["kind"] == "service_event")
    assert ok["verified"] == 1
    assert bad["verified"] == 0          # 11:30 is in the document, but not in this claim's quote
