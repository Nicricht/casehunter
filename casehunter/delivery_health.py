from .database import row_to_dict, transaction, utc_now


DELIVERY_FAILURE_TABLE = """
CREATE TABLE IF NOT EXISTS delivery_failures (
    email TEXT PRIMARY KEY,
    failure_kind TEXT NOT NULL,
    reason TEXT,
    provider_message_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
)
"""

UNUSABLE_FAILURE_KINDS = {"INVALID", "BLOCKED", "BOUNCED"}


def _ensure_table(conn):
    conn.execute(DELIVERY_FAILURE_TABLE)


def mark_delivery_failure(email, failure_kind, reason=None, provider_message_id=None, db_path=None):
    address = (email or "").strip().lower()
    kind = (failure_kind or "BOUNCED").strip().upper()
    if not address:
        raise ValueError("Falta el correo que falló")
    if kind not in UNUSABLE_FAILURE_KINDS:
        kind = "BOUNCED"
    now = utc_now()
    with transaction(db_path) as conn:
        _ensure_table(conn)
        existing = conn.execute(
            "SELECT email,first_seen_at FROM delivery_failures WHERE email=?",
            (address,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE delivery_failures
                   SET failure_kind=?,reason=?,provider_message_id=?,last_seen_at=?
                   WHERE email=?""",
                (kind, reason, provider_message_id, now, address),
            )
        else:
            conn.execute(
                """INSERT INTO delivery_failures(
                       email,failure_kind,reason,provider_message_id,first_seen_at,last_seen_at
                   ) VALUES(?,?,?,?,?,?)""",
                (address, kind, reason, provider_message_id, now, now),
            )
        row = conn.execute("SELECT * FROM delivery_failures WHERE email=?", (address,)).fetchone()
    return row_to_dict(row)


def get_delivery_failure(email, db_path=None):
    address = (email or "").strip().lower()
    if not address:
        return None
    with transaction(db_path) as conn:
        _ensure_table(conn)
        row = conn.execute("SELECT * FROM delivery_failures WHERE email=?", (address,)).fetchone()
    return row_to_dict(row) if row else None


def is_unusable_email(email, db_path=None):
    failure = get_delivery_failure(email, db_path)
    return bool(failure and failure.get("failure_kind") in UNUSABLE_FAILURE_KINDS)


def list_delivery_failures(db_path=None):
    with transaction(db_path) as conn:
        _ensure_table(conn)
        rows = conn.execute("SELECT * FROM delivery_failures ORDER BY last_seen_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]
