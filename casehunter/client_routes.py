from datetime import datetime, timezone

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .client_auth import (
    authenticate_client,
    create_client_session,
    create_client_user,
    get_client_session,
    list_client_users,
    reset_client_password,
    revoke_client_session,
    set_client_user_status,
)
from .client_portal import build_client_portfolio
from .repository import get_company


CLIENT_SESSION_COOKIE = "case_hunter_client_session"


class ClientLogin(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ClientUserCreate(BaseModel):
    company_id: int
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default="VIEWER", max_length=30)


class ClientUserStatusUpdate(BaseModel):
    status: str = Field(min_length=3, max_length=20)


class ClientPasswordReset(BaseModel):
    password: str = Field(min_length=12, max_length=256)


def _cookie_secure(request):
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _require_admin_auth_configured(app):
    if not app.state.auth_username or not app.state.auth_password:
        raise HTTPException(
            status_code=503,
            detail="Configura CASE_HUNTER_USERNAME y CASE_HUNTER_PASSWORD antes de administrar accesos cliente.",
        )


def _current_client(request, app):
    token = request.cookies.get(CLIENT_SESSION_COOKIE)
    user = get_client_session(token, app.state.db_path)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión de cliente requerida")
    return user


def register_client_routes(app, static_dir):
    @app.get("/client", include_in_schema=False)
    def client_portal_page():
        return FileResponse(static_dir / "client.html")

    @app.post("/api/client/login")
    def client_login(payload: ClientLogin, request: Request):
        user = authenticate_client(payload.email, payload.password, app.state.db_path)
        if not user:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")
        token, expires_at = create_client_session(user["id"], app.state.db_path)
        company = get_company(user["company_id"], app.state.db_path)
        response = JSONResponse({
            "user": user,
            "company": {"id": company["id"], "name": company["name"], "rut": company.get("rut")},
        })
        seconds = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        response.set_cookie(
            CLIENT_SESSION_COOKIE,
            token,
            max_age=seconds,
            httponly=True,
            secure=_cookie_secure(request),
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/client/logout")
    def client_logout(request: Request):
        token = request.cookies.get(CLIENT_SESSION_COOKIE)
        revoke_client_session(token, app.state.db_path)
        response = JSONResponse({"ok": True})
        response.delete_cookie(CLIENT_SESSION_COOKIE, path="/")
        return response

    @app.get("/api/client/me")
    def client_me(request: Request):
        user = _current_client(request, app)
        company = get_company(user["company_id"], app.state.db_path)
        return {
            "user": user,
            "company": {"id": company["id"], "name": company["name"], "rut": company.get("rut")},
        }

    @app.get("/api/client/portfolio")
    def client_portfolio(request: Request):
        user = _current_client(request, app)
        return build_client_portfolio(user["company_id"], app.state.db_path)

    @app.get("/api/admin/client-users")
    def admin_list_client_users():
        _require_admin_auth_configured(app)
        return list_client_users(app.state.db_path)

    @app.post("/api/admin/client-users", status_code=201)
    def admin_create_client_user(payload: ClientUserCreate):
        _require_admin_auth_configured(app)
        try:
            return create_client_user(
                payload.company_id,
                payload.email,
                payload.password,
                payload.role,
                app.state.db_path,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/admin/client-users/{user_id}/status")
    def admin_update_client_user_status(user_id: int, payload: ClientUserStatusUpdate):
        _require_admin_auth_configured(app)
        try:
            return set_client_user_status(user_id, payload.status, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/admin/client-users/{user_id}/password")
    def admin_reset_client_password(user_id: int, payload: ClientPasswordReset):
        _require_admin_auth_configured(app)
        try:
            return reset_client_password(user_id, payload.password, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
