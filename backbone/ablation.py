"""Ablation: what would the weekly verdicts be under common naive rules?

Each variant edits a temporary copy of the reconciled encounters the way a naive pipeline would treat them, then
re-runs the SAME projection (weekly_compliance). Output: out/ablation.json and a printed table.
Run: python -m backbone.ablation
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import date
from pathlib import Path

from .db import DEFAULT_DB, ROOT, connect
from .project import SqlLog, weekly_compliance
from .query import Scope

MRN, START, END = "HG-M042", date(2026, 1, 5), date(2026, 1, 30)


def _variants():
    k = lambda e: f"{MRN}|{e}"  # noqa: E731
    return {
        "this system": [],
        "scheduled group duration (ignore breaks, late arrival, early departure)": [
            ("UPDATE encounters SET minutes_low=90, minutes_high=90 WHERE mrn=? AND service_type='group_therapy' "
             "AND eligible='yes'", (MRN,))],
        "latest-received document wins (E110 departure 11:30 from the Jan 26 resend)": [
            ("UPDATE encounters SET minutes_low=75, minutes_high=75 WHERE encounter_key=?", (k("HG-E110"),))],
        "draft note / posted charge counts as attendance (E116)": [
            ("UPDATE encounters SET eligible='yes', minutes_low=75, minutes_high=75 WHERE encounter_key=?", (k("HG-E116"),))],
        "pick the primary note for disputed E115 (50 min)": [
            ("UPDATE encounters SET minutes_low=50, minutes_high=50 WHERE encounter_key=?", (k("HG-E115"),))],
        "pick the later-signed note for disputed E115 (40 min)": [
            ("UPDATE encounters SET minutes_low=40, minutes_high=40 WHERE encounter_key=?", (k("HG-E115"),))],
        "stated session length for E119 (45 min, incl. partner-only part)": [
            ("UPDATE encounters SET minutes_low=45, minutes_high=45 WHERE encounter_key=?", (k("HG-E119"),))],
        "partner-only collateral counts as family therapy (E109, 40 min)": [
            ("UPDATE encounters SET eligible='yes', service_type='family_therapy', minutes_low=40, minutes_high=40 "
             "WHERE encounter_key=?", (k("HG-E109"),))],
    }


def run() -> dict:
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for name, edits in _variants().items():
            p = Path(td) / "a.db"
            shutil.copy(DEFAULT_DB, p)
            conn = connect(p)
            with conn:
                for sql, params in edits:
                    conn.execute(sql, params)
            weeks = weekly_compliance(conn, MRN, START, END, SqlLog(), Scope)
            out[name] = {w["week_start"]: {"status": w["status"],
                                           "minutes": [w["evaluations"][0]["totals"]["minutes"]["low"],
                                                       w["evaluations"][0]["totals"]["minutes"]["high"]],
                                           "days": w["evaluations"][0]["totals"]["therapy_days"]["low"]}
                         for w in weeks}
            conn.close()
    base = out["this system"]
    lines = ["| Variant | W1 Jan 5 | W2 Jan 12 | W3 Jan 19 | W4 Jan 26 |", "|---|---|---|---|---|"]
    for name, weeks in out.items():
        cells = []
        for wk, v in weeks.items():
            m = v["minutes"][0] if v["minutes"][0] == v["minutes"][1] else f"{v['minutes'][0]}–{v['minutes'][1]}"
            flip = "" if name == "this system" or v["status"] == base[wk]["status"] else " ⚠"
            cells.append(f"{v['status']} ({v['days']}d, {m}m){flip}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    (ROOT / "out" / "ablation.json").write_text(json.dumps(out, indent=2))
    (ROOT / "out" / "ablation.md").write_text(table + "\n")
    print(table)
    return out


if __name__ == "__main__":
    run()
