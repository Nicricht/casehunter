from .database import transaction, utc_now
from .portfolio_discovery import scan_registered_portfolio
from .public_watch import configure_case_watch


BOOTSTRAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_bootstrap_state (
    bootstrap_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_error TEXT,
    updated_at TEXT NOT NULL
);
"""

ALEMBIC_BOOTSTRAP_KEY = "alembic_rio_claro_pilot_v1"
ALEMBIC_CASE_EXTERNAL_ID = "MU271AW2265687"
ALEMBIC_PILOT_STARTED_ON = "2026-09-09"


def _ensure_schema(db_path=None):
    with transaction(db_path) as conn:
        conn.executescript(BOOTSTRAP_SCHEMA)


def _state(bootstrap_key, db_path=None):
    _ensure_schema(db_path)
    with transaction(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM production_bootstrap_state WHERE bootstrap_key=?",
            (bootstrap_key,),
        ).fetchone()
    return dict(row) if row else None


def _save_state(bootstrap_key, status, error=None, db_path=None):
    now = utc_now()
    with transaction(db_path) as conn:
        conn.execute(
            """INSERT INTO production_bootstrap_state(bootstrap_key,status,last_error,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(bootstrap_key) DO UPDATE SET
                   status=excluded.status,last_error=excluded.last_error,updated_at=excluded.updated_at""",
            (bootstrap_key, status, (error or None), now),
        )


def bootstrap_alembic_pilot(db_path=None, scanner=None, force=False):
    """Seed the first real pilot from registered public sources exactly once.

    The bootstrap deliberately requires the exact official Ley Lobby identifier
    for Río Claro. It never promotes a fuzzy company-name match into a pilot.
    Once the marker is DONE, regular portfolio refresh + public watch own the
    lifecycle and this function becomes a no-op.
    """
    existing_state = _state(ALEMBIC_BOOTSTRAP_KEY, db_path)
    if existing_state and existing_state.get("status") == "DONE" and not force:
        return {
            "status": "SKIPPED",
            "reason": "already_bootstrapped",
            "bootstrap_key": ALEMBIC_BOOTSTRAP_KEY,
        }

    try:
        portfolio = scan_registered_portfolio(
            "alembic_pharmaceuticals",
            db_path=db_path,
            scanner=scanner,
            max_pages=5,
            enrich_limit=40,
        )

        with transaction(db_path) as conn:
            row = conn.execute(
                """SELECT id,company_id,status FROM cases
                   WHERE external_id=? ORDER BY id DESC LIMIT 1""",
                (ALEMBIC_CASE_EXTERNAL_ID,),
            ).fetchone()
            if row is None:
                raise RuntimeError(
                    "No se encontró el caso oficial MU271AW2265687 después de refrescar la cartera Alembic"
                )
            case_id = int(row["id"])
            if row["company_id"] is None:
                raise RuntimeError("El caso Alembic no quedó vinculado a la empresa canónica")

            now = utc_now()
            conn.execute(
                "UPDATE cases SET status='FOLLOW_UP',updated_at=? WHERE id=? AND status NOT IN ('RESOLVED','DISMISSED')",
                (now, case_id),
            )

            pilot_event = conn.execute(
                """SELECT id FROM timeline_events
                   WHERE case_id=? AND event_type='PILOT_STARTED' LIMIT 1""",
                (case_id,),
            ).fetchone()
            if pilot_event is None:
                conn.execute(
                    """INSERT INTO timeline_events(
                           case_id,event_type,event_date,title,details,source_url,created_at
                       ) VALUES(?,'PILOT_STARTED',?,'Piloto de seguimiento iniciado',?,?,?)""",
                    (
                        case_id,
                        ALEMBIC_PILOT_STARTED_ON,
                        "La empresa aceptó que Case Hunter continúe el seguimiento activo del caso.",
                        "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758/936913",
                        now,
                    ),
                )

            watch_action = conn.execute(
                """SELECT id FROM actions
                   WHERE case_id=? AND action_type='WATCH_PUBLIC_CASE' AND status='TODO'
                   LIMIT 1""",
                (case_id,),
            ).fetchone()
            if watch_action is None:
                conn.execute(
                    """INSERT INTO actions(
                           case_id,action_type,title,status,due_date,responsible,note,created_at
                       ) VALUES(?,'WATCH_PUBLIC_CASE',?,'TODO',NULL,'Case Hunter',?,?)""",
                    (
                        case_id,
                        "Mantener vigilancia activa del caso y reportar únicamente cambios relevantes",
                        "Piloto Alembic / Río Claro. Vigilar fuentes públicas y generar acciones solo ante cambios materiales.",
                        now,
                    ),
                )

        watch_sources = configure_case_watch(case_id, db_path=db_path)
        _save_state(ALEMBIC_BOOTSTRAP_KEY, "DONE", db_path=db_path)
        return {
            "status": "DONE",
            "bootstrap_key": ALEMBIC_BOOTSTRAP_KEY,
            "case_id": case_id,
            "portfolio": portfolio,
            "watch_source_count": len(watch_sources),
        }
    except Exception as exc:
        _save_state(ALEMBIC_BOOTSTRAP_KEY, "ERROR", str(exc)[:1000], db_path=db_path)
        raise
