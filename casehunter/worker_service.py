import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .auto_service import run_auto_cycle
from .database import backend_name, connect, init_db

LOGGER = logging.getLogger("casehunter.worker")
INTERVAL_MINUTES = max(60, int(os.getenv("CASE_HUNTER_AUTO_INTERVAL_MINUTES", "360")))
RUN_ON_START = os.getenv("CASE_HUNTER_WORKER_RUN_ON_START", "1").strip().lower() not in {"0", "false", "no"}


async def _automation_loop(app):
    if not RUN_ON_START:
        await asyncio.sleep(INTERVAL_MINUTES * 60)
    else:
        await asyncio.sleep(10)
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
        "last_run": app.state.last_run,
    }
    return JSONResponse(payload, status_code=200 if database_ok else 503)
