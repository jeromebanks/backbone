"""Reconciliation follow-ups #87, #88 and #89: hand-built claims, no LLM, no source documents.

Weeks are Mon–Sun; 2026-02-02 is a Monday.
"""
from __future__ import annotations

import copy
import json
import random

from backbone.reconcile import reconcile_patient

from helpers import assessment, event, with_docs


def items(label, score, date, values, *, form_id="F1", copy_=False, sha=None):
    a = assessment(label, score=score, date=date, form_id=form_id, copy=copy_, sha=sha)
    a.payload["item_scores"] = list(values)
    return a


def canonical(res) -> str:
    return json.dumps([res.assessments, [{k: v for k, v in e.items() if not k.startswith("_")} for e in res.encounters],
                       res.decisions, res.conflicts], sort_keys=True, default=str)


def shuffled_runs(claims, seed, n=10):
    rng = random.Random(seed)
    for _ in range(n):
        cs = copy.deepcopy(claims)
        rng.shuffle(cs)
        yield reconcile_patient("P1", cs)


# ---------------------------------------------------------------- #87 per-item assessment scores

def test_disagreeing_item_values_give_a_conflict_and_no_definite_item_value():
    claims = with_docs(items("portal", 14, "2026-02-02", ["Item 9: 0", "Item 1: 2"]),
                       items("clinic", 14, "2026-02-02", ["Item 9: 1", "Item 1: 2"]))
    for order in (claims, list(reversed(claims))):
        res = reconcile_patient("P1", copy.deepcopy(order))
        (a,) = res.assessments
        assert a["item_scores"] == ["Item 1: 2", "Item 9: disputed"], a      # the agreeing item keeps its value
        assert a["total_score"] == 14                                       # the total is not disputed
        (c,) = [c for c in res.conflicts if c["field"] == "item_scores"]
        assert c["subject_key"] == a["assessment_key"]
        assert [x["value"] for x in c["candidates"]] == ["Item 9: 0", "Item 9: 1"]
        assert all(len(x["claim_ids"]) == 1 for x in c["candidates"])
        assert any(d["rule"] == "R8" and d["outcome"] == "item_disputed" and "Item 9" in d["reason"]
                   for d in res.decisions)


def test_agreeing_and_silent_items_are_one_value_each():
    claims = with_docs(items("portal", 14, "2026-02-02", ["Item 9: 0"]),
                       items("clinic", 14, "2026-02-02", ["Item 9: 0", "Item 2: 1"]),
                       items("third", 14, "2026-02-02", []))
    res = reconcile_patient("P1", claims)
    (a,) = res.assessments
    assert a["item_scores"] == ["Item 2: 1", "Item 9: 0"]
    assert not res.conflicts


def test_a_copys_items_carry_no_weight():
    claims = with_docs(items("portal", 14, "2026-02-02", ["Item 9: 0"]),
                       items("import", 14, "2026-02-02", ["Item 9: 1"], copy_=True))
    res = reconcile_patient("P1", claims)
    (a,) = res.assessments
    assert a["item_scores"] == ["Item 9: 0"] and not res.conflicts
    (d,) = [d for d in res.decisions if d["outcome"] == "copy_not_distinct"]
    assert "Item 9: 1" in d["reason"]


# ---------------------------------------------------------------- #88 one form ID on two dates

def test_one_form_on_two_dates_is_one_assessment_with_a_date_conflict():
    claims = with_docs(assessment("portal", score=14, date="2026-01-16", form_id="Q1"),
                       assessment("clinic", score=14, date="2026-01-17", form_id="Q1"))
    for res in shuffled_runs(claims, 88):
        (a,) = res.assessments
        assert (a["form_id"], a["status"], a["total_score"]) == ("Q1", "disputed", 14), a
        assert a["completed_date"] == "2026-01-16"           # anchored on the earliest stated date, still queryable
        assert len(a["claim_ids"]) == 2
        (c,) = [c for c in res.conflicts if c["field"] == "completed_date"]
        assert c["subject_key"] == a["assessment_key"]
        assert [x["value"] for x in c["candidates"]] == ["2026-01-16", "2026-01-17"]
        assert any(d["rule"] == "R8" and d["outcome"] == "date_disputed" for d in res.decisions)


def test_a_form_whose_copy_states_another_date_is_not_disputed():
    claims = with_docs(assessment("portal", score=14, date="2026-01-16", form_id="Q1"),
                       assessment("import", score=14, date="2026-01-17", form_id="Q1", copy=True))
    res = reconcile_patient("P1", claims)
    (a,) = res.assessments
    assert (a["completed_date"], a["status"]) == ("2026-01-16", "distinct")
    assert len(a["copy_claim_ids"]) == 1 and not res.conflicts


def test_a_formless_record_joins_the_form_on_its_date():
    claims = with_docs(assessment("portal", score=14, date="2026-01-16", form_id="Q1"),
                       assessment("note", score=14, date="2026-01-16"),
                       assessment("clinic", score=14, date="2026-01-17", form_id="Q1"),
                       assessment("other", score=9, date="2026-01-20"))
    res = reconcile_patient("P1", claims)
    by_form = {a["form_id"]: a for a in res.assessments}
    assert set(by_form) == {"Q1", None}
    assert len(by_form["Q1"]["claim_ids"]) == 3
    assert (by_form[None]["completed_date"], by_form[None]["total_score"]) == ("2026-01-20", 9)


def test_two_forms_on_one_day_stay_two_assessments():
    claims = with_docs(assessment("portal", score=14, date="2026-01-16", form_id="Q1"),
                       assessment("clinic", score=9, date="2026-01-16", form_id="Q2"))
    res = reconcile_patient("P1", claims)
    assert sorted((a["form_id"], a["total_score"], a["status"]) for a in res.assessments) == [
        ("Q1", 14, "distinct"), ("Q2", 9, "distinct")]
    assert not res.conflicts


# ---------------------------------------------------------------- #89 R7 and an ambiguous record's accounts

def _ambiguous_register(own_overlap=False):
    """E1 and E2 are psychotherapy contacts of other types; the ID-less register overlaps both (#78). With
    `own_overlap`, E1's and E2's own notes also overlap each other, which is a real overlap R7 must still flag."""
    return with_docs(
        event("note-ind", eid="E1", stype="individual_therapy", contact=[("10:00", "11:00" if own_overlap else "10:50")]),
        event("note-fam", eid="E2", stype="family_therapy", contact=[("10:50", "11:40")]),
        event("register", eid=None, stype="group_therapy", etype="attendance_record",
              arrival="10:40", departure="11:00"))


def test_ambiguous_record_over_two_contacts_gives_one_note_and_no_overlap_flags():
    res = reconcile_patient("P1", _ambiguous_register())
    r7 = [d for d in res.decisions if d["rule"] == "R7"]
    assert not [d for d in r7 if d["outcome"] == "overlap"], [d["reason"] for d in r7]
    assert not [f for e in res.encounters for f in e["flags"] if "overlap" in f]
    (note,) = [d for d in r7 if d["outcome"] == "ambiguous_account"]
    assert note["subject_key"] == "P1|E1"
    assert "P1|E1" in note["reason"] and "P1|E2" in note["reason"] and "register" in note["reason"]
    assert len(note["claim_ids"]) == 1


def test_a_real_overlap_between_the_contacts_is_still_flagged():
    res = reconcile_patient("P1", _ambiguous_register(own_overlap=True))
    overlap = [d["reason"] for d in res.decisions if d["rule"] == "R7" and d["outcome"] == "overlap"]
    assert overlap and all("10:00–11:00 vs" in r and "10:50–11:40" in r for r in overlap), overlap
    assert not any("10:40–11:00" in r for r in overlap), overlap
    assert len([d for d in res.decisions if d["outcome"] == "ambiguous_account"]) == 1


def test_an_own_record_sharing_the_ambiguous_records_times_is_still_compared():
    """E1's note states the register's times, so R6 holds them as one presence account of both records. E1's and
    E2's own notes still overlap each other: that is two contacts at once and must be flagged."""
    res = reconcile_patient("P1", with_docs(
        event("note-ind", eid="E1", stype="individual_therapy", contact=[("10:40", "11:00")]),
        event("note-fam", eid="E2", stype="family_therapy", contact=[("10:50", "11:40")]),
        event("register", eid=None, stype="group_therapy", etype="attendance_record",
              arrival="10:40", departure="11:00")))
    overlap = [d["reason"] for d in res.decisions if d["rule"] == "R7" and d["outcome"] == "overlap"]
    assert any("P1|E1 10:40–11:00 vs P1|E2 10:50–11:40" in r for r in overlap), overlap
    assert len([d for d in res.decisions if d["outcome"] == "ambiguous_account"]) == 1


def test_ambiguity_note_is_order_independent():
    want = None
    for res in shuffled_runs(_ambiguous_register(), 89):
        got = canonical(res)
        assert want is None or got == want
        want = got
