import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .auto_service import run_auto_cycle
from .database import backend_name, connect, init_db
from .production_bootstrap import ALEMBIC_CASE_EXTERNAL_ID, ALEMBIC_BOOTSTRAP_KEY, bootstrap_alembic_pilot

LOGGER = logging.getLogger("uvicorn.error")
LOGGER.setLevel(logging.INFO)
INTERVAL_MINUTES = max(60, int(os.getenv("CASE_HUNTER_AUTO_INTERVAL_MINUTES", "360")))
RUN_ON_START = os.getenv("CASE_HUNTER_WORKER_RUN_ON_START", "1").strip().lower() not in {"0", "false", "no"}
BOOTSTRAP_ALEMBIC = os.getenv("CASE_HUNTER_BOOTSTRAP_ALEMBIC", "0").strip().lower() in {"1", "true", "yes"}


def _query_one(sql, params=()):
    connection = connect()
    try:
        return connection.execute(sql, params).fetchone()
    except Exception:
        return None
    finally:
        connection.close()


def _production_snapshot():
    """Return a sanitized production state summary suitable for logs and healthchecks."""
    snapshot = {"database_backend": backend_name()}

    total_cases = _query_one("SELECT COUNT(*) AS count FROM cases")
    snapshot["case_count"] = int(total_cases["count"]) if total_cases else None

    case = _query_one(
        "SELECT id,company_id,status FROM cases WHERE external_id=? ORDER BY id DESC LIMIT 1",
        (ALEMBIC_CASE_EXTERNAL_ID,),
    )
    if case:
        case_id = int(case["id"])
        snapshot["alembic_case"] = {
            "id": case_id,
            "company_id": int(case["company_id"]) if case["company_id"] is not None else None,
            "status": case["status"],
        }

        watch_sources = _query_one(
            "SELECT COUNT(*) AS count FROM case_watch_sources WHERE case_id=? AND status='ACTIVE'",
            (case_id,),
        )
        snapshot["active_watch_sources"] = int(watch_sources["count"]) if watch_sources else None

        watch_events = _query_one(
            "SELECT COUNT(*) AS count FROM case_watch_events WHERE case_id=?",
            (case_id,),
        )
        snapshot["watch_event_count"] = int(watch_events["count"]) if watch_events else None

        watch_action = _query_one(
            """SELECT COUNT(*) AS count FROM actions
               WHERE case_id=? AND action_type='WATCH_PUBLIC_CASE' AND status='TODO'""",
            (case_id,),
        )
        snapshot["watch_action_count"] = int(watch_action["count"]) if watch_action else None
    else:
        snapshot["alembic_case"] = None
        snapshot["active_watch_sources"] = None
        snapshot["watch_event_count"] = None
        snapshot["watch_action_count"] = None

    bootstrap = _query_one(
        "SELECT status,updated_at FROM production_bootstrap_state WHERE bootstrap_key=?",
        (ALEMBIC_BOOTSTRAP_KEY,),
    )
    snapshot["bootstrap_state"] = (
        {"status": bootstrap["status"], "updated_at": bootstrap["updated_at"]} if bootstrap else None
    )

    last_run = _query_one(
        "SELECT id,status,started_at,finished_at,cases_created,cases_updated,messages_sent "
        "FROM automation_runs ORDER BY id DESC LIMIT 1"
    )
    snapshot["latest_automation_run"] = dict(last_run) if last_run else None
    return snapshot


def _bootstrap_summary(value):
    value = value or {}
    return {
        "status": value.get("status"),
        "reason": value.get("reason"),
        "case_id": value.get("case_id"),
        "watch_source_count": value.get("watch_source_count"),
    }


async def _automation_loop(app):
    if not RUN_ON_START:
        await asyncio.sleep(INTERVAL_MINUTES * 60)
    else:
        await asyncio.sleep(10)

    if BOOTSTRAP_ALEMBIC:
        try:
            app.state.bootstrap = await asyncio.to_thread(bootstrap_alembic_pilot)
            LOGGER.info(
                "Alembic production bootstrap completed: %s snapshot=%s",
                _bootstrap_summary(app.state.bootstrap),
                _production_snapshot(),
            )
        except Exception as exc:
            LOGGER.exception("Alembic production bootstrap failed")
            app.state.bootstrap = {"status": "ERROR", "error": type(exc).__name__}

    while True:
        try:
            result = await asyncio.to_thread(run_auto_cycle)
            app.state.last_run = {
                "ok": True,
                "run_id": result.get("run_id"),
                "cases_created": result.get("cases_created", 0),
                "cases_updated": result.get("cases_updated", 0),
                "messages_sent": result.get("messages_sent", 0),
            }
            LOGGER.info("Case Hunter worker cycle completed: %s snapshot=%s", app.state.last_run, _production_snapshot())
        except Exception as exc:
            LOGGER.exception("Case Hunter worker cycle failed")
            app.state.last_run = {"ok": False, "error": type(exc).__name__}
        await asyncio.sleep(INTERVAL_MINUTES * 60)


def _database_ok():
    connection = connect()
    try:
        row = connection.execute("SELECT 1 AS ok").fetchone()
        return bool(row and int(row["ok"]) == 1)
    finally:
        connection.close()


@asynccontextmanager
async def lifespan(app):
    init_db()
    app.state.last_run = None
    app.state.bootstrap = None
    LOGGER.info("Case Hunter worker startup snapshot=%s", _production_snapshot())
    task = asyncio.create_task(_automation_loop(app))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Case Hunter Worker", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    try:
        database_ok = _database_ok()
    except Exception:
        database_ok = False
    payload = {
        "status": "ok" if database_ok else "degraded",
        "database_backend": backend_name(),
        "database_ok": database_ok,
        "interval_minutes": INTERVAL_MINUTES,
        "bootstrap": getattr(app.state, "bootstrap", None),
        "last_run": getattr(app.state, "last_run", None),
        "production_snapshot": _production_snapshot(),
    }
    return JSONResponse(payload, status_code=200 if database_ok else 503)
