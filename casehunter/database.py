from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

from .config import DATABASE_PATH, DATABASE_URL
from .db_backends import connect_postgres, is_postgres_target

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rut TEXT UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT,
    detail_url TEXT,
    event_date TEXT,
    detected_company_name TEXT,
    company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
    agency TEXT,
    contract_ref TEXT,
    status TEXT NOT NULL DEFAULT 'DETECTED',
    confidence_label TEXT NOT NULL DEFAULT 'LOW',
    confidence_score REAL NOT NULL DEFAULT 0,
    financial_priority INTEGER NOT NULL DEFAULT 0,
    current_blocker TEXT,
    blocker_reason TEXT,
    raw_text TEXT,
    detail_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS case_problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    matched_patterns TEXT NOT NULL DEFAULT '[]',
    UNIQUE(case_id, type)
);

CREATE TABLE IF NOT EXISTS case_amounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    amount_clp INTEGER NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'public_record',
    note TEXT,
    UNIQUE(case_id, amount_clp, provenance)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNKNOWN',
    required INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(case_id, code)
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'TODO',
    due_date TEXT,
    responsible TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    pages_scanned INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    company_name TEXT,
    email TEXT NOT NULL,
    source_url TEXT,
    confidence_label TEXT NOT NULL DEFAULT 'LOW',
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(case_id, email)
);

CREATE TABLE IF NOT EXISTS contact_assessments (
    contact_id INTEGER PRIMARY KEY REFERENCES contacts(id) ON DELETE CASCADE,
    trust_score INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL DEFAULT 'REVIEW',
    reasons TEXT NOT NULL DEFAULT '[]',
    source_host TEXT,
    email_domain TEXT,
    assessed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    recipient_email TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEEDS_CONTACT',
    dedupe_key TEXT NOT NULL UNIQUE,
    approved_at TEXT,
    sent_at TEXT,
    provider_message_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outreach_id INTEGER NOT NULL REFERENCES outreach_messages(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    provider_message_id TEXT NOT NULL UNIQUE,
    in_reply_to TEXT,
    sender_email TEXT,
    subject TEXT,
    body TEXT,
    classification TEXT NOT NULL,
    received_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outreach_id INTEGER NOT NULL REFERENCES outreach_messages(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'PENDING',
    due_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT,
    provider_message_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(outreach_id, sequence)
);

CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    source_urls TEXT NOT NULL DEFAULT '[]',
    scans_started INTEGER NOT NULL DEFAULT 0,
    cases_created INTEGER NOT NULL DEFAULT 0,
    cases_updated INTEGER NOT NULL DEFAULT 0,
    contacts_found INTEGER NOT NULL DEFAULT 0,
    drafts_created INTEGER NOT NULL DEFAULT 0,
    messages_sent INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS automation_source_state (
    source_url TEXT PRIMARY KEY,
    cursor_index INTEGER NOT NULL DEFAULT 0,
    last_total INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contacts_case ON contacts(case_id);
CREATE INDEX IF NOT EXISTS idx_contact_assessments_decision ON contact_assessments(decision, trust_score);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach_messages(status);
CREATE INDEX IF NOT EXISTS idx_outreach_case ON outreach_messages(case_id);
CREATE INDEX IF NOT EXISTS idx_replies_case ON outreach_replies(case_id);
CREATE INDEX IF NOT EXISTS idx_replies_outreach ON outreach_replies(outreach_id);
CREATE INDEX IF NOT EXISTS idx_followups_status_due ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_followups_outreach ON followups(outreach_id);
CREATE INDEX IF NOT EXISTS idx_automation_started ON automation_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_company ON cases(company_id);
CREATE INDEX IF NOT EXISTS idx_cases_event_date ON cases(event_date);
CREATE INDEX IF NOT EXISTS idx_actions_case_status ON actions(case_id, status);
CREATE INDEX IF NOT EXISTS idx_timeline_case_date ON timeline_events(case_id, event_date);
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _database_target(path=None):
    if path is not None:
        return path
    return DATABASE_URL or DATABASE_PATH


def backend_name(path=None):
    return "postgresql" if is_postgres_target(_database_target(path)) else "sqlite"


def connect(path=None):
    target = _database_target(path)
    if is_postgres_target(target):
        return connect_postgres(str(target))

    db_path = Path(target)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(path=None):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    return dict(row) if row is not None else None


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default
