from .database import row_to_dict, transaction, utc_now


VALID_COMMERCIAL_STATUSES = {
    "OPEN",
    "PILOT_PROPOSED",
    "PILOT_ACTIVE",
    "WON",
    "LOST",
}

COMMERCIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS commercial_opportunities (
    case_id INTEGER NOT NULL REFERENCES cases(id) UNIQUE,
    status TEXT NOT NULL DEFAULT 'OPEN',
    pilot_price_clp INTEGER,
    monthly_price_clp INTEGER,
    expected_value_clp INTEGER,
    lost_reason TEXT,
    note TEXT,
    pilot_started_at TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commercial_status ON commercial_opportunities(status);
CREATE INDEX IF NOT EXISTS idx_commercial_updated ON commercial_opportunities(updated_at);
"""


def ensure_commercial_schema(db_path=None):
    with transaction(db_path) as conn:
        conn.executescript(COMMERCIAL_SCHEMA)


def get_commercial_row(case_id, db_path=None):
    ensure_commercial_schema(db_path)
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM commercial_opportunities WHERE case_id=?",
            (int(case_id),),
        ).fetchone()
    return row_to_dict(row)


def save_commercial_row(
    case_id,
    status,
    pilot_price_clp=None,
    monthly_price_clp=None,
    expected_value_clp=None,
    lost_reason=None,
    note=None,
    pilot_started_at=None,
    closed_at=None,
    db_path=None,
):
    status = str(status or "").strip().upper()
    if status not in VALID_COMMERCIAL_STATUSES:
        raise ValueError("Estado comercial no válido")

    ensure_commercial_schema(db_path)
    now = utc_now()
    with transaction(db_path) as conn:
        exists = conn.execute("SELECT id FROM cases WHERE id=?", (int(case_id),)).fetchone()
        if exists is None:
            raise KeyError("Caso no encontrado")
        conn.execute(
            """INSERT INTO commercial_opportunities(
                   case_id,status,pilot_price_clp,monthly_price_clp,expected_value_clp,
                   lost_reason,note,pilot_started_at,closed_at,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(case_id) DO UPDATE SET
                   status=excluded.status,
                   pilot_price_clp=excluded.pilot_price_clp,
                   monthly_price_clp=excluded.monthly_price_clp,
                   expected_value_clp=excluded.expected_value_clp,
                   lost_reason=excluded.lost_reason,
                   note=excluded.note,
                   pilot_started_at=excluded.pilot_started_at,
                   closed_at=excluded.closed_at,
                   updated_at=excluded.updated_at""",
            (
                int(case_id), status, pilot_price_clp, monthly_price_clp, expected_value_clp,
                lost_reason, note, pilot_started_at, closed_at, now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM commercial_opportunities WHERE case_id=?",
            (int(case_id),),
        ).fetchone()
    return row_to_dict(row)
