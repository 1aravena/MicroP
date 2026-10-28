"""Migraciones encadenadas con respaldo y actualizacion atomica a esquema 3."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

from .errors import StorageError

SCHEMA_VERSION = 3
SCHEMA_2 = """
CREATE TABLE collection_sessions (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, responsible TEXT NOT NULL,
 partition_name TEXT NOT NULL CHECK(partition_name IN ('train','test')),
 source TEXT NOT NULL CHECK(source IN ('real','simulated')),
 conditions TEXT NOT NULL, notes TEXT NOT NULL,
 created_at TEXT NOT NULL, closed_at TEXT,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed'))
);
CREATE TABLE trials (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, trial_id TEXT NOT NULL UNIQUE,
 session_id TEXT NOT NULL REFERENCES collection_sessions(session_id),
 scenario TEXT NOT NULL, expected_label TEXT NOT NULL CHECK(expected_label IN ('normal','anomalo')),
 notes TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, ended_at TEXT,
 status TEXT NOT NULL CHECK(status IN ('prepared','starting','running','stopping','completed','interrupted')),
 end_reason TEXT, reviewed INTEGER CHECK(reviewed IN (0,1)), reviewed_at TEXT, review_notes TEXT NOT NULL DEFAULT '',
 analysis_state TEXT NOT NULL DEFAULT 'pending' CHECK(analysis_state IN ('pending','processing','ready','error')),
 analysis_error TEXT, analysis_summary_json TEXT NOT NULL DEFAULT '{}', feature_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE trial_captures (
 trial_id TEXT NOT NULL REFERENCES trials(trial_id),
 origin TEXT NOT NULL CHECK(origin IN ('UNO','NANO')),
 capture_id TEXT NOT NULL UNIQUE REFERENCES captures(capture_id),
 PRIMARY KEY(trial_id,origin)
);
CREATE TABLE observations (
 observation_id TEXT PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(trial_id),
 feature_version INTEGER NOT NULL, window_index INTEGER NOT NULL,
 started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
 features_json TEXT NOT NULL, quality_json TEXT NOT NULL, reasons_json TEXT NOT NULL,
 eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
 UNIQUE(trial_id,feature_version,window_index)
);
CREATE INDEX trial_session_order ON trials(session_id,ordinal);
CREATE INDEX trial_analysis ON trials(analysis_state,status);
CREATE INDEX observation_trial ON observations(trial_id,window_index);
CREATE INDEX sample_capture_time ON samples(capture_id,received_at,id);
PRAGMA user_version = 2;
"""

SCHEMA_3 = """
CREATE TABLE access_attempts (
 ordinal INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL UNIQUE,
 at TEXT NOT NULL, decision TEXT NOT NULL, authorization TEXT NOT NULL, signal TEXT NOT NULL,
 reason TEXT NOT NULL, snapshot_json TEXT NOT NULL
);
CREATE TABLE access_policy (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), failures INTEGER NOT NULL DEFAULT 0,
 window_started REAL NOT NULL DEFAULT 0, blocked_until REAL NOT NULL DEFAULT 0
);
INSERT INTO access_policy(singleton) VALUES(1);
CREATE TABLE ml_predictions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, model_id TEXT,
 uno_capture TEXT NOT NULL REFERENCES captures(capture_id), nano_capture TEXT NOT NULL REFERENCES captures(capture_id),
 started_at TEXT NOT NULL, ended_at TEXT NOT NULL, created_at TEXT NOT NULL,
 label TEXT, score REAL, features_json TEXT NOT NULL, quality_json TEXT NOT NULL, reasons_json TEXT NOT NULL,
 UNIQUE(run_id,started_at)
);
CREATE INDEX prediction_recent ON ml_predictions(id);
PRAGMA user_version = 3;
"""


def upgrade(connection, path, *, backup=True):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version == SCHEMA_VERSION:
        return None
    if version not in (1, 2):
        raise StorageError(f'Esquema SQLite no compatible: {version}. No se borro la base.')
    backup_path = None
    if backup and str(path) != ':memory:':
        suffix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup_path = Path(f'{path}.schema{version}-{suffix}-{uuid.uuid4().hex[:8]}.bak')
        with sqlite3.connect(backup_path) as destination:
            connection.backup(destination)
    try:
        scripts = (SCHEMA_2 if version == 1 else '') + '\n' + SCHEMA_3
        connection.executescript('BEGIN IMMEDIATE;\n' + scripts + '\nCOMMIT;')
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return str(backup_path) if backup_path else None
