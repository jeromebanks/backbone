"""SQLite persistence. Two layers:

evidence layer   documents, extractions, claims            (append-only; produced by ingest/extract)
clinical layer   patients, encounters, encounter_intervals,  (derived; rebuilt per patient by reconcile.py)
                 plan_requirements, assessments, observations, decisions, conflicts
projection       v_encounter_week, v_patient_week            (SQL views over the clinical layer)
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

CREATE TABLE IF NOT EXISTS patients (
    mrn   TEXT PRIMARY KEY,
    name  TEXT,
    dob   TEXT,
    reconciled_at TEXT,
    ruleset_version TEXT
);

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


def connect_readonly(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DEFAULT_DB)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
