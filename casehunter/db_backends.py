import re


SERIAL_ID_TABLES = {
    "companies",
    "cases",
    "case_problems",
    "case_amounts",
    "documents",
    "actions",
    "timeline_events",
    "scans",
    "contacts",
    "outreach_messages",
    "outreach_replies",
    "followups",
    "automation_runs",
}


def is_postgres_target(value):
    text = str(value or "").strip().lower()
    return text.startswith("postgresql://") or text.startswith("postgres://")


def _translate_sql(sql):
    text = str(sql)
    ignored = re.match(r"^(\s*)INSERT\s+OR\s+IGNORE\s+INTO\s+", text, flags=re.I)
    if ignored:
        text = re.sub(r"^(\s*)INSERT\s+OR\s+IGNORE\s+INTO\s+", r"\1INSERT INTO ", text, count=1, flags=re.I)
        if " ON CONFLICT " not in text.upper():
            text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    # Case Hunter SQL uses ? exclusively as DB-API placeholders, never as a
    # literal operator. psycopg uses %s for positional parameters.
    text = text.replace("?", "%s")
    return text


def postgres_schema(sqlite_schema):
    schema = sqlite_schema.replace("PRAGMA foreign_keys = ON;", "")
    schema = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", schema, flags=re.I)
    schema = re.sub(r"(\b(?:case|company|contact|outreach)_id\b)\s+INTEGER(\s+(?:NOT\s+NULL\s+)?REFERENCES)", r"\1 BIGINT\2", schema, flags=re.I)
    return schema


class PostgresCursor:
    def __init__(self, raw_cursor, lastrowid=None):
        self._raw = raw_cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._raw.rowcount

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()

    def __iter__(self):
        return iter(self._raw)


class PostgresConnection:
    """Small compatibility layer for the SQLite-shaped repository API.

    It intentionally exposes only the methods Case Hunter uses. This lets the
    domain/repository code stay backend-agnostic while SQLite remains the local
    default and PostgreSQL can provide persistent production storage.
    """

    backend = "postgresql"

    def __init__(self, dsn):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requiere psycopg. Instala requirements.txt.") from exc
        self._raw = psycopg.connect(dsn, row_factory=dict_row)

    def execute(self, sql, params=()):
        original = str(sql)
        translated = _translate_sql(original)
        cursor = self._raw.execute(translated, tuple(params or ()))
        lastrowid = None
        match = re.match(r"^\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)", translated, flags=re.I)
        plain_insert = " ON CONFLICT " not in translated.upper()
        if match and plain_insert and match.group(1).lower() in SERIAL_ID_TABLES and cursor.rowcount > 0:
            id_row = self._raw.execute("SELECT LASTVAL() AS id").fetchone()
            if id_row:
                lastrowid = int(id_row["id"])
        return PostgresCursor(cursor, lastrowid)

    def executescript(self, script):
        schema = postgres_schema(script)
        for statement in schema.split(";"):
            sql = statement.strip()
            if sql:
                self._raw.execute(sql)
        return self

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()


def connect_postgres(dsn):
    return PostgresConnection(dsn)
