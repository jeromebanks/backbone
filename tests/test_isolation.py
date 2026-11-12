"""Patient and document isolation in the query layer (issue #2).

Encounter IDs are only unique within a patient, and document labels (`doc_label`) are not unique at all:
`documents.sha256` is the identity. These tests build a tiny abstraction by hand (no LLM, no extraction cache)
in which two patients reuse the same encounter ID and the same document label, and check that the timeline
operator never attaches one patient's (or one document's) relations to another.
"""
from __future__ import annotations

import pytest

from backbone import ingest as ingest_mod
from backbone.db import connect
from backbone.ingest import ingest
from backbone.query import QueryPlan, Scope, TimelineStep, execute_plan
from backbone.reconcile import reconcile_patients
from backbone.schema import DocumentInfo, Extraction, Relation, ServiceEvent

PERIOD = dict(start="2026-01-05", end="2026-01-30")
EVENT_LINE = "Individual therapy 2026-01-07 10:00-10:50, completed."
COMPANION_LINE = "Co-therapist record of encounter E1."
CORRECTION_LINE = "Correction to encounter E1: departure 10:50 should read 10:40."


def _event() -> ServiceEvent:
    return ServiceEvent(
        encounter_id="E1", related_encounter_id=None, appointment_id=None, service_date="2026-01-07",
        service_type="individual_therapy", modality="in_person", evidence_type="clinical_note",
        disposition="attended", patient_present="yes", scheduled=None, patient_arrival=None,
        patient_departure=None, patient_contact_intervals=[{"start": "10:00", "end": "10:50"}],
        nontherapeutic_intervals=[], stated_minutes=None, clinicians=[], quotes=[EVENT_LINE])


def _companion() -> Relation:
    return Relation(type="companion_record", encounter_id="E1", field=None, old_value=None, new_value=None,
                    form_id=None, original_date="2026-01-07", quote=COMPANION_LINE)


def _correction() -> Relation:
    return Relation(type="corrects_field", encounter_id="E1", field="departure", old_value="10:50",
                    new_value="10:40", form_id=None, original_date="2026-01-07", quote=CORRECTION_LINE)


def _doc(tmp_path, monkeypatch_map, filename, *, mrn, name, title, relation: Relation, extra_line: str):
    """Write a document whose header label is NOTE and register the extraction the fake 'LLM' returns for it."""
    f = tmp_path / filename
    f.write_text(f"Document ID: NOTE\nPatient: {name} | MRN {mrn}\n{EVENT_LINE}\n{extra_line}\n")
    monkeypatch_map[filename] = Extraction(
        document=DocumentInfo(document_id="NOTE", title=title, signed=True, signed_at=None, received_at=None,
                              finality="final", patient_name=name, patient_mrn=mrn, patient_dob=None,
                              relations=[relation]),
        service_events=[_event()], assessments=[], observations=[], plan_requirements=[])
    return f


def _build(tmp_path, monkeypatch, docs: list[tuple]):
    conn = connect(tmp_path / "iso.db")
    extractions: dict[str, Extraction] = {}
    files = [_doc(tmp_path, extractions, *d[:1], **d[1]) for d in docs]

    def fake_extract(sha, filename, text, **kw):
        return extractions[filename], {"from_cache": False, "latency_ms": 0}
    monkeypatch.setattr(ingest_mod, "extract_document", fake_extract)
    monkeypatch.setattr("backbone.extract.complete_json",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    stats = ingest(conn, files, log=lambda *a: None, workers=1)
    assert not stats["failed"]
    reconcile_patients(conn, stats["affected_patients"])
    labels = {r["doc_label"] for r in conn.execute("SELECT doc_label FROM documents")}
    assert labels == {"NOTE"}, labels      # the label collision is real
    return conn


def _documents(conn, patients) -> list[dict]:
    step = TimelineStep(scope=Scope(patients=patients, include_evidence=False, **PERIOD), kinds=["documents"])
    facts = execute_plan(conn, QueryPlan(question="t", steps=[step]))["results"][0]["facts"]
    return [f for f in facts if f["kind"] == "document"]


def _relation_types(d: dict) -> list[str]:
    return [r["type"] for r in d.get("relations", [])]


@pytest.fixture
def two_patients(tmp_path, monkeypatch):
    """P1 and P2 both have encounter E1, each recorded in a document labelled NOTE. Only P2's NOTE corrects E1."""
    return _build(tmp_path, monkeypatch, [
        ("p1_note.txt", dict(mrn="P1", name="Pat One", title="P1 note", relation=_companion(),
                             extra_line=COMPANION_LINE)),
        ("p2_note.txt", dict(mrn="P2", name="Pat Two", title="P2 note", relation=_correction(),
                             extra_line=CORRECTION_LINE)),
    ])


def test_timeline_relations_stay_within_patient(two_patients):
    docs = _documents(two_patients, ["P1"])
    assert [d["title"] for d in docs] == ["P1 note"]
    # P1's own companion relation is shown (positive control); P2's correction of *its* E1 is not.
    assert _relation_types(docs[0]) == ["companion_record"]


def test_timeline_keeps_same_label_documents_of_two_patients_apart(two_patients):
    docs = _documents(two_patients, "all")
    by_title = {d["title"]: d for d in docs}
    assert sorted(by_title) == ["P1 note", "P2 note"], [d["title"] for d in docs]
    assert all(d["doc_id"] == "NOTE" and len(d["assertions"]) == 1 for d in docs)
    assert _relation_types(by_title["P1 note"]) == ["companion_record"]
    assert _relation_types(by_title["P2 note"]) == ["corrects_field"]


def test_timeline_keeps_same_label_documents_of_one_patient_apart(tmp_path, monkeypatch):
    """Two different documents (different bytes) of the same patient that share a label stay two documents,
    each carrying only the relations it states."""
    conn = _build(tmp_path, monkeypatch, [
        ("note_a.txt", dict(mrn="P1", name="Pat One", title="first NOTE", relation=_companion(),
                            extra_line=COMPANION_LINE)),
        ("note_b.txt", dict(mrn="P1", name="Pat One", title="second NOTE", relation=_correction(),
                            extra_line=CORRECTION_LINE)),
    ])
    docs = _documents(conn, ["P1"])
    by_title = {d["title"]: d for d in docs}
    assert sorted(by_title) == ["first NOTE", "second NOTE"], [d["title"] for d in docs]
    assert all(len(d["assertions"]) == 1 for d in docs)
    assert _relation_types(by_title["first NOTE"]) == ["companion_record"]
    assert _relation_types(by_title["second NOTE"]) == ["corrects_field"]


def test_timeline_hides_unverified_relations(tmp_path, monkeypatch):
    # The correction's quote is not in the document, so its claim is unverified (R0) and must not reach output.
    conn = _build(tmp_path, monkeypatch, [
        ("p1_note.txt", dict(mrn="P1", name="Pat One", title="P1 note", relation=_correction(),
                             extra_line=COMPANION_LINE)),
    ])
    assert conn.execute("SELECT verified FROM claims WHERE kind='relation'").fetchone()[0] == 0
    docs = _documents(conn, ["P1"])
    assert [d["title"] for d in docs] == ["P1 note"] and _relation_types(docs[0]) == []
