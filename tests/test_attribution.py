"""Patient attribution at ingest (issues #1 and #5). Hand-built extractions, temp DB, no LLM, no cache."""
import pytest

from backbone import ingest as ingest_mod
from backbone.answer import directory
from backbone.db import ROOT, connect
from backbone.ingest import discover, ingest
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, ServiceEvent


def extraction(line: str, *, name=None, mrn=None, dob=None, eid="X1", date="2026-01-07") -> Extraction:
    """One attended individual-therapy session whose only quote is `line` (must appear in the file text)."""
    return Extraction(
        document=DocumentInfo(document_id=None, title="t", signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name=name, patient_mrn=mrn, patient_dob=dob, relations=[]),
        service_events=[ServiceEvent(
            encounter_id=eid, related_encounter_id=None, appointment_id=None, service_date=date,
            service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
            disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
            patient_departure=None, patient_contact_intervals=[{"start": "10:00", "end": "10:50"}],
            nontherapeutic_intervals=[], stated_minutes=None, clinicians=[], quotes=[line])],
        assessments=[], observations=[], plan_requirements=[])


SESSION = "Individual therapy 2026-01-07 10:00-10:50, completed."


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp DB plus a fake extractor that returns whatever `by_file[filename]` currently holds."""
    by_file: dict = {}

    def fake_extract(sha, name, text, **k):
        return by_file[name], {"from_cache": False}

    monkeypatch.setattr(ingest_mod, "extract_document", fake_extract)
    conn = connect(tmp_path / "t.db")

    def run(*files, **kw):
        stats = ingest(conn, list(files), log=lambda *a: None, **kw)
        reconcile_patients(conn, stats["affected_patients"])
        return stats

    return conn, tmp_path, by_file, run


def encounter_mrns(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM encounters"))


def patient_mrns(conn) -> list[str]:
    return sorted(r[0] for r in conn.execute("SELECT mrn FROM patients"))


# ---------------------------------------------------------------- #1: missing MRNs must not merge patients

def test_two_mrnless_patients_are_not_merged(env):
    conn, tmp, by_file, run = env
    a, b = tmp / "a.txt", tmp / "b.txt"
    a.write_text(f"Patient: Alex Doe | DOB 1980-01-01\n{SESSION}\n")
    b.write_text(f"Patient: Blair Roe | DOB 1990-02-02\n{SESSION}\n")
    by_file["a.txt"] = extraction(SESSION, name="Alex Doe", dob="1980-01-01")
    by_file["b.txt"] = extraction(SESSION, name="Blair Roe", dob="1990-02-02")
    stats = run(a, b)
    # Neither document can be tied to a known patient: both are held back, not pooled under one identity.
    assert stats["affected_patients"] == []
    assert patient_mrns(conn) == [] and encounter_mrns(conn) == []
    assert sorted(q["status"] for q in stats["quarantined"]) == ["no_patient_identity"] * 2
    # The evidence is kept (claims are append-only evidence), just unattributed.
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE patient_mrn IS NULL").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE patient_mrn IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 2


def test_mrnless_document_matching_one_known_patient_is_attributed(env):
    conn, tmp, by_file, run = env
    first, second = tmp / "first.txt", tmp / "second.txt"
    first.write_text(f"Patient: Alex Doe | DOB 1980-01-01 | MRN ZZ-1\n{SESSION}\n")
    line2 = "Individual therapy 2026-01-08 10:00-10:50, completed."
    second.write_text(f"Patient: Alex Doe | DOB 1980-01-01\n{line2}\n")
    by_file["first.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1", dob="1980-01-01")
    by_file["second.txt"] = extraction(line2, name="Alex Doe", dob="1980-01-01", eid="X2", date="2026-01-08")
    run(first)
    stats = run(second)
    assert stats["affected_patients"] == ["ZZ-1"] and stats["quarantined"] == []
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-1"]


def test_mrnless_document_matching_two_known_patients_is_quarantined(env):
    conn, tmp, by_file, run = env
    p1, p2, amb = tmp / "p1.txt", tmp / "p2.txt", tmp / "amb.txt"
    p1.write_text(f"Patient: Alex Doe | DOB 1980-01-01 | MRN ZZ-1\n{SESSION}\n")
    p2.write_text(f"Patient: Alex Doe | DOB 1975-05-05 | MRN ZZ-2\n{SESSION}\n")
    line = "Individual therapy 2026-01-09 10:00-10:50, completed."
    amb.write_text(f"Patient: Alex Doe\n{line}\n")       # name only: matches both known patients
    by_file["p1.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1", dob="1980-01-01")
    by_file["p2.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-2", dob="1975-05-05")
    by_file["amb.txt"] = extraction(line, name="Alex Doe", eid="X9", date="2026-01-09")
    run(p1, p2)
    stats = run(amb)
    assert stats["affected_patients"] == []
    assert [q["status"] for q in stats["quarantined"]] == ["ambiguous_patient"]
    assert stats["quarantined"][0]["candidates"] == ["ZZ-1", "ZZ-2"]
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-2"]       # neither patient gained the X9 session


def test_multi_patient_roster_is_quarantined(env):
    conn, tmp, by_file, run = env
    roster = tmp / "roster.txt"
    line = "Group therapy 2026-01-07 10:00-10:50, attended."
    roster.write_text("Group attendance roster\n"
                      "Alex Doe | MRN: ZZ-1 | Attended\n"
                      "Blair Roe | MRN: ZZ-2 | Attended\n"
                      f"{line}\n")
    # The extraction schema holds one patient identity per document; the LLM picked the first row.
    by_file["roster.txt"] = extraction(line, name="Alex Doe", mrn="ZZ-1")
    stats = run(roster)
    assert stats["affected_patients"] == []
    assert [q["status"] for q in stats["quarantined"]] == ["multi_patient"]
    assert stats["quarantined"][0]["candidates"] == ["ZZ-1", "ZZ-2"]
    assert patient_mrns(conn) == [] and encounter_mrns(conn) == []


def test_mrns_in_text_finds_labelled_identifiers():
    assert ingest_mod.mrns_in_text("Patient: A | MRN: ab-12\nMRN AB-12.\n") == {"AB-12"}
    assert ingest_mod.mrns_in_text("MRN: ZZ-1, MRN #ZZ-2;") == {"ZZ-1", "ZZ-2"}
    assert ingest_mod.mrns_in_text("No identifiers here; mrnx is not a label.") == set()


def test_guard_fires_on_no_corpus_document():
    """The multi-patient guard must not fire on the supplied documents (golden results must not move).
    The end-to-end check (no quarantine when ingesting the corpus) is in test_pipeline.py."""
    files = discover([ROOT / "documents"])
    assert files and all(len(ingest_mod.mrns_in_text(f.read_text())) == 1 for f in files)


# ---------------------------------------------------------------- #5: re-attribution clears the former owner

def _p1_document(env):
    conn, tmp, by_file, run = env
    f = tmp / "note.txt"
    # Both identifiers are printed, neither MRN-labelled nor phrased as a correction (#42/#43 would act on those), so
    # which patient owns the document is decided by the extraction alone: what these #5 tests vary.
    f.write_text(f"Patient: Alex Doe | chart ZZ-1 (record merged into ZZ-2)\n{SESSION}\n")
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    stats = run(f)
    assert stats["affected_patients"] == ["ZZ-1"]
    assert encounter_mrns(conn) == ["ZZ-1"]                  # precondition: P1 owns a derived encounter
    return f


def test_reextraction_moving_document_clears_old_patient(env):
    conn, tmp, by_file, run = env
    f = _p1_document(env)
    # Same bytes (same sha), new extractor output: the MRN now reads ZZ-2.
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-2")
    stats = run(f, model="re-extract")
    assert encounter_mrns(conn) == ["ZZ-2"]
    assert stats["affected_patients"] == ["ZZ-1", "ZZ-2"]
    assert patient_mrns(conn) == ["ZZ-2"]
    assert "ZZ-1" not in directory(conn)
    assert conn.execute("SELECT patient_mrn FROM documents").fetchone()[0] == "ZZ-2"
    for t in ("decisions", "plan_requirements", "assessments", "observations", "conflicts"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t} WHERE mrn='ZZ-1'").fetchone()[0] == 0, t


def test_reextraction_into_quarantine_clears_old_patient(env):
    conn, tmp, by_file, run = env
    f = _p1_document(env)
    by_file["note.txt"] = extraction(SESSION)              # neither MRN nor name extracted any more
    stats = run(f, model="re-extract")
    assert encounter_mrns(conn) == [] and patient_mrns(conn) == []
    assert stats["affected_patients"] == ["ZZ-1"]
    assert [q["status"] for q in stats["quarantined"]] == ["no_patient_identity"]
    assert conn.execute("SELECT patient_mrn FROM documents").fetchone()[0] is None


def test_reextraction_keeps_patient_that_still_has_other_documents(env):
    conn, tmp, by_file, run = env
    f = _p1_document(env)
    other = tmp / "other.txt"
    line = "Individual therapy 2026-01-14 10:00-10:50, completed."
    other.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{line}\n")
    by_file["other.txt"] = extraction(line, name="Alex Doe", mrn="ZZ-1", eid="X3", date="2026-01-14")
    run(other)
    by_file["note.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-2")
    run(f, model="re-extract")
    assert encounter_mrns(conn) == ["ZZ-1", "ZZ-2"]
    assert patient_mrns(conn) == ["ZZ-1", "ZZ-2"]


def test_name_only_document_matches_patient_created_in_same_batch(env):
    conn, tmp, by_file, run = env
    with_mrn, name_only = tmp / "with_mrn.txt", tmp / "name_only.txt"
    with_mrn.write_text(f"Patient: Alex Doe | DOB 1980-01-01 | MRN ZZ-1\n{SESSION}\n")
    line = "Individual therapy 2026-01-08 10:00-10:50, completed."
    name_only.write_text(f"Patient: Alex Doe | DOB 1980-01-01\n{line}\n")
    by_file["with_mrn.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1", dob="1980-01-01")
    by_file["name_only.txt"] = extraction(line, name="Alex Doe", dob="1980-01-01", eid="X2", date="2026-01-08")
    stats = run(name_only, with_mrn)        # attribution must not depend on sha order within one batch
    assert stats["quarantined"] == [] and encounter_mrns(conn) == ["ZZ-1", "ZZ-1"]


def test_extraction_without_latency_is_not_reported_as_failed(env):
    # The progress log used to index meta['latency_ms'] and put a successfully ingested document in `failed`.
    conn, tmp, by_file, run = env
    f = tmp / "one.txt"
    f.write_text(f"Patient: Alex Doe | MRN ZZ-1\n{SESSION}\n")
    by_file["one.txt"] = extraction(SESSION, name="Alex Doe", mrn="ZZ-1")
    stats = run(f)
    assert stats["failed"] == [] and stats["affected_patients"] == ["ZZ-1"]
