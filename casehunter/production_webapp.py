from starlette.responses import JSONResponse

from .database import backend_name, connect
from .webapp import app as inner_app


def database_health():
    connection = connect()
    try:
        row = connection.execute("SELECT 1 AS ok").fetchone()
        ok = bool(row and int(row["ok"]) == 1)
        return {
            "status": "ok" if ok else "degraded",
            "database_backend": backend_name(),
            "database_ok": ok,
        }
    finally:
        connection.close()


async def app(scope, receive, send):
    if scope.get("type") == "http" and scope.get("path") == "/healthz":
        try:
            payload = database_health()
            status_code = 200 if payload["database_ok"] else 503
        except Exception:
            payload = {
                "status": "degraded",
                "database_backend": backend_name(),
                "database_ok": False,
            }
            status_code = 503
        response = JSONResponse(payload, status_code=status_code)
        await response(scope, receive, send)
        return
    await inner_app(scope, receive, send)
