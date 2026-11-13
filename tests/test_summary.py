"""`plan --summary` readout shows uncertain contributions, undated rejections, alternatives (#75), and survives an
evaluation without a metric (#72)."""
from backbone.summary import summarize

SCOPE = {"patients": ["P1"], "start": "2026-01-05", "end": "2026-01-11", "service_types": None}


def _res(**step):
    return {"results": [{"op": step.pop("op", "timeline"), "params": {"scope": SCOPE}, "totals": {}, "groups": [],
                         "facts": [], "exclusions": [], "conflicts": [], "evidence": [], **step}]}


def test_summary_shows_uncertain_contribution():
    f = {"encounter": "E2", "date": "2026-01-06", "service_type": "individual_therapy", "disposition": "attended",
         "counts_as_therapy_session": "uncertain", "patient_present_minutes": {"low": 50, "high": 50},
         "counted_minutes": {"low": 0, "high": 50}, "records": ["D1"]}
    assert "counted=0–50" in summarize(_res(facts=[f]))


def test_summary_marks_undated_rejections():
    x = {"encounter": None, "date": None, "service_type": None, "reason": "date not stated", "records": ["D1"],
         "rule": "R0", "patient": "P1", "record_kind": "observation", "claim_id": "abc:observation:1",
         "undated": True, "unstated_dates": ["date"]}
    out = summarize(_res(exclusions=[x]))
    assert "EXCLUDED (undated; unstated: date) observation abc:observation:1" in out and "None None None" not in out


def test_summary_shows_identity_alternatives_on_documents():
    d = {"kind": "document", "doc_id": "D1", "title": "t", "signed_at": None, "received_at": None, "finality": "final",
         "assertions": [{"encounter": "E1", "record_type": "clinical_note", "disposition": "attended", "arrival": None,
                         "departure": None, "contact_intervals": [], "nontherapeutic": [], "stated_minutes": None,
                         "identity_alternatives": ["E1~2026-01-07-group_therapy"]}]}
    assert "alternatives=['E1~2026-01-07-group_therapy']" in summarize(_res(facts=[d]))


def test_summary_survives_requirement_without_metric():
    g = {"week_start": "2026-01-05", "status": "UNDETERMINED", "notes": [],
         "evaluations": [{"totals": {}, "minutes_calculation": "", "requirements": [
             {"requirement": "P1|plan|D1|other|2026-01-05", "status": "UNDETERMINED", "reason": "unsupported metric other"}]}]}
    assert "UNDETERMINED" in summarize(_res(op="compliance", groups=[g]))


def test_summary_cites_shared_label_documents_with_their_sha():
    # #84: a shared label must be cited as "LABEL [sha12]"; the summary must show it.
    ev = {"doc_id": "NOTE", "doc_sha": "0a1b2c3d4e5f", "file": "n.txt", "record_type": "clinical_note",
          "passages": [{"lines": "4", "quote": "q"}]}
    d = {"kind": "document", "doc_id": "NOTE", "doc_sha": "0a1b2c3d4e5f", "title": "t", "signed_at": None,
         "received_at": None, "finality": "final", "assertions": []}
    out = summarize(_res(evidence=[ev], facts=[d]))
    assert "EVIDENCE (NOTE [0a1b2c3d4e5f] L4)" in out and "DOC NOTE [0a1b2c3d4e5f] (" in out
