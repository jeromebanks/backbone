"""SQLite persistence.

evidence layer   documents, extractions, claims                (ingest/extract; a document's claims are replaced
                                                                when it is re-extracted, never edited by reconcile)
attribution      quarantine, identifier_changes, attribution_notes  (ingest: unattributable documents, MRN
                                                                corrections stated in text, non-default attribution)
bookkeeping      pending_reconcile                             (patients whose evidence changed, not yet reconciled;
                                                                cleared by trigger when reconcile stamps the patient)
patients         patients                                      (created at attribution; reconcile stamps
                                                                reconciled_at and removes a patient left with nothing)
clinical layer   encounters, encounter_intervals,              (derived; rebuilt per patient by reconcile.py)
                 plan_requirements, assessments, observations, decisions, conflicts
projection       v_encounter_week                              (SQL view: each encounter with its Monday week start)
operations       answer_cache, run_log

`connect()` applies the DDL (read-write). `connect_readonly()` opens the file read-only and never runs DDL.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("BACKBONE_DB", ROOT / "out" / "backbone.db"))

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    sha256        TEXT PRIMARY KEY,           -- identity of the bytes; byte-identical files dedupe here
    doc_label     TEXT NOT NULL,              -- header Document ID (e.g. BH-D103) or filename stem
    paths         TEXT NOT NULL,              -- JSON list of every path these bytes were ingested from
    text          TEXT NOT NULL,
    patient_mrn   TEXT,
    ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_patient ON documents(patient_mrn);
CREATE INDEX IF NOT EXISTS ix_documents_label ON documents(doc_label);   -- shared-label lookups (#40, #57)

CREATE TABLE IF NOT EXISTS extractions (
    sha256            TEXT NOT NULL REFERENCES documents(sha256),
    extractor_version TEXT NOT NULL,
    model             TEXT NOT NULL,
    raw_json          TEXT NOT NULL,
    latency_ms        INTEGER,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cost_usd          REAL,
    from_cache        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    PRIMARY KEY (sha256, extractor_version, model)
);

-- A claim = one assertion one document makes about one subject, with verified evidence spans.
CREATE TABLE IF NOT EXISTS claims (
    claim_id      TEXT PRIMARY KEY,           -- sha256[:12]:kind:index  (stable across rebuilds)
    sha256        TEXT NOT NULL REFERENCES documents(sha256),
    doc_label     TEXT NOT NULL,
    patient_mrn   TEXT,
    kind          TEXT NOT NULL,              -- document | service_event | relation | assessment | observation | plan_requirement
    subject_key   TEXT,                       -- encounter id / form id / etc.
    evidence_type TEXT,
    payload       TEXT NOT NULL,              -- JSON of the extracted item
    evidence      TEXT NOT NULL,              -- JSON list [{quote, line_start, line_end, match}]
    verified      INTEGER NOT NULL            -- 1 if every quote was located in the document text
);
CREATE INDEX IF NOT EXISTS ix_claims_patient ON claims(patient_mrn, kind);
CREATE INDEX IF NOT EXISTS ix_claims_subject ON claims(subject_key);
CREATE INDEX IF NOT EXISTS ix_claims_doc ON claims(sha256);

-- Documents ingest could not attribute to exactly one patient. Their claims are kept with patient_mrn NULL, so they
-- are evidence but take part in no patient's reconciliation. Every ingest re-runs attribution for quarantined and
-- name-matched documents from their stored extraction, so a row is cleared once the document can be attributed.
CREATE TABLE IF NOT EXISTS quarantine (
    sha256         TEXT PRIMARY KEY REFERENCES documents(sha256),
    doc_label      TEXT NOT NULL,
    status         TEXT NOT NULL,             -- no_patient_identity | ambiguous_patient | multi_patient | mrn_mismatch
    reason         TEXT NOT NULL,
    candidates     TEXT NOT NULL,             -- JSON list of candidate MRNs (empty when none)
    quarantined_at TEXT NOT NULL
);

-- Explicit MRN corrections stated in a document's text ("MRN X corrected to Y"). The stating document is attributed to
-- Y, and attribution resolves every other document carrying X to Y as well (chains followed; a fork or cycle resolves
-- nothing and quarantines the document as ambiguous_patient) (#53). Not recorded for multi_patient documents.
CREATE TABLE IF NOT EXISTS identifier_changes (
    sha256   TEXT NOT NULL REFERENCES documents(sha256),
    old_mrn  TEXT NOT NULL,
    new_mrn  TEXT NOT NULL,
    quote    TEXT NOT NULL,
    line     INTEGER,
    PRIMARY KEY (sha256, old_mrn, new_mrn)
);

-- Why a document was attributed the way it was, when the basis is not simply the MRN the extraction reported
-- (printed_mrn: the text's single printed MRN, the extraction had none (#55); identifier_change: another document's
-- explicit MRN correction (#53)). Evidence-layer bookkeeping, rewritten whenever the document is (re-)attributed.
CREATE TABLE IF NOT EXISTS attribution_notes (
    sha256  TEXT PRIMARY KEY REFERENCES documents(sha256),
    mrn     TEXT NOT NULL,
    basis   TEXT NOT NULL,                    -- printed_mrn | identifier_change
    reason  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    mrn   TEXT PRIMARY KEY,
    name  TEXT,
    dob   TEXT,
    reconciled_at TEXT,
    ruleset_version TEXT
);

-- Patients whose evidence changed and who still need reconciling. Written in the same transaction as the claims, so
-- a crash before reconciliation cannot leave the clinical layer silently stale: the next ingest or reconcile picks
-- them up. No FK to patients (a former owner may be deleted). Cleared by the triggers below, atomically with
-- reconcile.persist() (which stamps reconciled_at) or with the removal of an orphaned patient.
CREATE TABLE IF NOT EXISTS pending_reconcile (
    mrn       TEXT PRIMARY KEY,
    marked_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_pending_cleared_on_reconcile AFTER UPDATE OF reconciled_at ON patients
BEGIN DELETE FROM pending_reconcile WHERE mrn = NEW.mrn; END;
CREATE TRIGGER IF NOT EXISTS trg_pending_cleared_on_patient_delete AFTER DELETE ON patients
BEGIN DELETE FROM pending_reconcile WHERE mrn = OLD.mrn; END;

CREATE TABLE IF NOT EXISTS encounters (
    encounter_key    TEXT PRIMARY KEY,         -- mrn|encounter_id (or mrn|U-date-type-n when unidentified)
    mrn              TEXT NOT NULL,
    encounter_id     TEXT,
    service_date     TEXT NOT NULL,
    service_type     TEXT NOT NULL,
    modality         TEXT,
    disposition      TEXT NOT NULL,
    attended         TEXT NOT NULL,            -- yes | no | disputed | unknown
    patient_present  TEXT NOT NULL,            -- yes | no | partial | unknown
    is_therapy       INTEGER NOT NULL,
    eligible         TEXT NOT NULL,            -- yes | no | disputed   (counts as a therapy session)
    exclusion_reason TEXT,
    minutes_low      REAL,
    minutes_high     REAL,
    minutes_status   TEXT NOT NULL,            -- established | disputed | unknown | not_applicable
    calculation      TEXT,
    claim_ids        TEXT NOT NULL,            -- JSON list of supporting claim ids
    flags            TEXT NOT NULL,            -- JSON list of review flags
    ruleset_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_enc_patient_date ON encounters(mrn, service_date);
CREATE INDEX IF NOT EXISTS ix_enc_type ON encounters(service_type);

CREATE TABLE IF NOT EXISTS encounter_intervals (
    encounter_key TEXT NOT NULL REFERENCES encounters(encounter_key) ON DELETE CASCADE,
    kind          TEXT NOT NULL,               -- present | excluded | scheduled
    start_min     INTEGER NOT NULL,
    end_min       INTEGER NOT NULL,
    label         TEXT,
    claim_ids     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_intervals_enc ON encounter_intervals(encounter_key);

CREATE TABLE IF NOT EXISTS plan_requirements (
    requirement_key TEXT PRIMARY KEY,
    mrn             TEXT NOT NULL,
    doc_label       TEXT NOT NULL,
    metric          TEXT NOT NULL,
    comparator      TEXT NOT NULL,
    threshold       REAL NOT NULL,
    period          TEXT NOT NULL,
    counted_types   TEXT NOT NULL,             -- JSON list
    requires_patient_present INTEGER NOT NULL,
    effective_start TEXT,
    effective_end   TEXT,
    signed_at       TEXT,
    claim_ids       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plan_patient ON plan_requirements(mrn, effective_start, effective_end);

CREATE TABLE IF NOT EXISTS assessments (
    assessment_key TEXT PRIMARY KEY,
    mrn            TEXT NOT NULL,
    instrument     TEXT NOT NULL,
    total_score    REAL,
    item_scores    TEXT NOT NULL,
    completed_date TEXT,
    form_id        TEXT,
    status         TEXT NOT NULL,              -- distinct | disputed
    claim_ids      TEXT NOT NULL,              -- primary evidence
    copy_claim_ids TEXT NOT NULL               -- copies/imports that are NOT separate assessments
);
CREATE INDEX IF NOT EXISTS ix_assess_patient ON assessments(mrn, completed_date);

CREATE TABLE IF NOT EXISTS observations (
    observation_key TEXT PRIMARY KEY,
    mrn       TEXT NOT NULL,
    obs_date  TEXT NOT NULL,
    domain    TEXT NOT NULL,
    source    TEXT NOT NULL,
    statement TEXT NOT NULL,
    claim_ids TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_patient ON observations(mrn, obs_date);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    mrn          TEXT NOT NULL,
    subject_key  TEXT NOT NULL,
    rule         TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    reason       TEXT NOT NULL,
    claim_ids    TEXT NOT NULL,
    ruleset_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisions_subject ON decisions(mrn, subject_key);
CREATE INDEX IF NOT EXISTS ix_decisions_rule ON decisions(rule, mrn);      -- R0 rejection lookups (#39, #57)

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    mrn          TEXT NOT NULL,
    subject_key  TEXT NOT NULL,
    field        TEXT NOT NULL,
    candidates   TEXT NOT NULL,               -- JSON [{value, claim_ids}]
    resolution   TEXT NOT NULL                -- disputed | resolved:<how>
);
CREATE INDEX IF NOT EXISTS ix_conflicts_subject ON conflicts(mrn, subject_key);

CREATE TABLE IF NOT EXISTS run_log (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    command    TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    details    TEXT
);

CREATE TABLE IF NOT EXISTS answer_cache (
    cache_key   TEXT PRIMARY KEY,             -- sha256(question + abstraction fingerprint + prompt versions)
    question    TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Projection: one row per encounter with its Monday-start week.
DROP VIEW IF EXISTS v_encounter_week;
CREATE VIEW v_encounter_week AS
SELECT e.*,
       date(e.service_date, '-' || ((CAST(strftime('%w', e.service_date) AS INTEGER) + 6) % 7) || ' days') AS week_start
FROM encounters e;
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


_SCHEMA: list[tuple[str, str, str]] | None = None


def _schema() -> list[tuple[str, str, str]]:
    """(type, name, sql) of every table and view the DDL defines, read from an in-memory copy (computed once)."""
    global _SCHEMA
    if _SCHEMA is None:
        mem = sqlite3.connect(":memory:")
        mem.executescript(DDL)
        _SCHEMA = [tuple(r) for r in mem.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")]
        mem.close()
    return _SCHEMA


def connect_readonly(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database without writing to it: no DDL touches the file (#45), so read-only commands leave it
    byte-identical. A database from an older version may lack newer tables or the week view; those are created as
    empty TEMP objects on this connection only (in memory), so readers see the current schema."""
    path = Path(path or DEFAULT_DB)
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for typ, name, sql in _schema():
        if name not in have:
            conn.execute(sql.replace(f"CREATE {typ.upper()} ", f"CREATE TEMP {typ.upper()} ", 1))
    return conn
