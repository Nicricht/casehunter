from pathlib import Path
from contextlib import asynccontextmanager
import base64
import hmac

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import DATABASE_PATH, DEFAULT_LEY_LOBBY_URL, AUTH_USERNAME, AUTH_PASSWORD
from .database import init_db
from .repository import (
    add_timeline_event,
    create_action,
    create_company,
    dashboard,
    get_case,
    link_case_company,
    list_cases,
    list_companies,
    update_action,
    update_case_status,
    update_case_blocker,
    update_document,
    apply_resolution_playbook,
)
from .portfolio_watch import list_portfolios
from .scanner_service import list_scans, run_ley_lobby_scan, run_mercado_publico_sync
from .schemas import (ActionCreate, ActionUpdate, AutoRunRequest, BlockerUpdate, CompanyCreate, CompanyLink, DocumentUpdate,
    OutreachApprove, OutreachRecipientUpdate, ScanRequest, StatusUpdate, TimelineCreate, MercadoPublicoSyncRequest)
from .resolution_playbook import list_playbooks
from .resolution_learning import apply_resolution_recommendation, resolution_recommendation
from .auto_service import auto_status, list_auto_runs, run_auto_cycle
from .contact_discovery import list_contacts
from .followup import list_followups, process_due_followups
from .gmail_service import imap_configured
from .operations import operations_snapshot
from .outreach import approve_outreach, attach_recipient, list_outreach, reject_outreach, send_outreach, smtp_configured
from .reply_monitor import list_replies, sync_replies

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(db_path=None, auth_username=None, auth_password=None):
    @asynccontextmanager
    async def lifespan(app):
        init_db(app.state.db_path)
        yield

    app = FastAPI(title="Case Hunter Resolve", version=__version__, lifespan=lifespan)
    app.state.db_path = db_path
    app.state.auth_username = AUTH_USERNAME if auth_username is None else auth_username
    app.state.auth_password = AUTH_PASSWORD if auth_password is None else auth_password

    @app.middleware("http")
    async def optional_basic_auth(request, call_next):
        username = app.state.auth_username
        password = app.state.auth_password
        if not username or not password:
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        valid = False
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                supplied_user, supplied_password = decoded.split(":", 1)
                valid = hmac.compare_digest(supplied_user, username) and hmac.compare_digest(supplied_password, password)
            except (ValueError, UnicodeDecodeError):
                valid = False
        if not valid:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Case Hunter Resolve"'})
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "database": str(app.state.db_path or DATABASE_PATH),
        }

    @app.get("/api/config")
    def config():
        from .mercado_publico import configured as mercado_publico_configured
        return {
            "default_ley_lobby_url": DEFAULT_LEY_LOBBY_URL,
            "mercado_publico_configured": mercado_publico_configured(),
            "smtp_configured": smtp_configured(),
            "imap_configured": imap_configured(),
        }

    @app.get("/api/dashboard")
    def get_dashboard():
        return dashboard(app.state.db_path)

    @app.get("/api/operations")
    def get_operations(top_limit: int = 10):
        return operations_snapshot(app.state.db_path, top_limit)

    @app.get("/api/playbooks")
    def get_playbooks():
        return list_playbooks()

    @app.get("/api/companies")
    def get_companies():
        return list_companies(app.state.db_path)

    @app.post("/api/companies", status_code=201)
    def post_company(payload: CompanyCreate):
        try:
            return create_company(payload.name, payload.rut, app.state.db_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/companies/{company_id}/mercado-publico/sync")
    def sync_mercado_publico(company_id: int, payload: MercadoPublicoSyncRequest):
        try:
            return run_mercado_publico_sync(company_id, payload.start_date, payload.end_date, db_path=app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/portfolios")
    def get_portfolios(
        min_cases: int = Query(default=2, ge=1, le=100),
        active_only: bool = True,
        search: str | None = Query(default=None, max_length=100),
    ):
        return list_portfolios(
            min_cases=min_cases,
            active_only=active_only,
            search=search,
            db_path=app.state.db_path,
        )

    @app.get("/api/cases")
    def get_cases(status: str | None = None, company_id: int | None = None, search: str | None = Query(default=None, max_length=100)):
        return list_cases(status=status, company_id=company_id, search=search, db_path=app.state.db_path)

    @app.get("/api/cases/{case_id}")
    def get_case_detail(case_id: int):
        try:
            return get_case(case_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/cases/{case_id}/recommendation")
    def get_case_recommendation(case_id: int):
        try:
            return resolution_recommendation(case_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/cases/{case_id}/recommendation/apply")
    def post_case_recommendation(case_id: int, min_confidence: int = Query(default=55, ge=0, le=100)):
        try:
            return apply_resolution_recommendation(case_id, app.state.db_path, min_confidence=min_confidence)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/cases/{case_id}/status")
    def patch_case_status(case_id: int, payload: StatusUpdate):
        try:
            return update_case_status(case_id, payload.status, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/cases/{case_id}/blocker")
    def patch_case_blocker(case_id: int, payload: BlockerUpdate):
        try:
            return update_case_blocker(case_id, payload.blocker, payload.reason, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cases/{case_id}/playbook/apply")
    def post_apply_playbook(case_id: int):
        try:
            return apply_resolution_playbook(case_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/cases/{case_id}/company")
    def patch_case_company(case_id: int, payload: CompanyLink):
        try:
            return link_case_company(case_id, payload.company_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/documents/{document_id}")
    def patch_document(document_id: int, payload: DocumentUpdate):
        try:
            return update_document(document_id, payload.status, payload.note, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cases/{case_id}/actions", status_code=201)
    def post_action(case_id: int, payload: ActionCreate):
        try:
            return create_action(case_id, payload.title, payload.action_type, payload.due_date, payload.responsible, payload.note, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/actions/{action_id}")
    def patch_action(action_id: int, payload: ActionUpdate):
        try:
            return update_action(action_id, payload.status, payload.note, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/cases/{case_id}/timeline", status_code=201)
    def post_timeline(case_id: int, payload: TimelineCreate):
        try:
            return add_timeline_event(case_id, payload.title, payload.details, payload.event_type, payload.event_date, payload.source_url, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/scans/ley-lobby")
    def post_scan(payload: ScanRequest):
        try:
            return run_ley_lobby_scan(payload.url, payload.max_pages, payload.enrich, payload.enrich_limit, app.state.db_path)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/scans")
    def get_scans(limit: int = 20):
        return list_scans(limit, app.state.db_path)

    @app.get("/api/auto/status")
    def get_auto_status():
        return auto_status(app.state.db_path)

    @app.get("/api/auto/runs")
    def get_auto_runs(limit: int = 20):
        return list_auto_runs(limit, app.state.db_path)

    @app.post("/api/auto/run")
    def post_auto_run(payload: AutoRunRequest):
        try:
            return run_auto_cycle(
                source_urls=payload.source_urls, min_priority=payload.min_priority, max_pages=payload.max_pages,
                enrich_limit=payload.enrich_limit, discover_contacts=payload.discover_contacts,
                send_approved=payload.send_approved, db_path=app.state.db_path,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/contacts")
    def get_contacts(case_id: int | None = None):
        return list_contacts(case_id, app.state.db_path)

    @app.get("/api/outreach")
    def get_outreach(status: str | None = None):
        return list_outreach(status, app.state.db_path)

    @app.patch("/api/outreach/{message_id}/recipient")
    def patch_outreach_recipient(message_id: int, payload: OutreachRecipientUpdate):
        try:
            return attach_recipient(message_id, payload.recipient_email, db_path=app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/outreach/{message_id}/approve")
    def post_outreach_approve(message_id: int, payload: OutreachApprove):
        try:
            return approve_outreach(message_id, payload.recipient_email, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/outreach/{message_id}/send")
    def post_outreach_send(message_id: int):
        try:
            return send_outreach(message_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/outreach/{message_id}/reject")
    def post_outreach_reject(message_id: int):
        try:
            return reject_outreach(message_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/replies")
    def get_replies(case_id: int | None = None, classification: str | None = None, limit: int = 100):
        return list_replies(case_id=case_id, classification=classification, limit=limit, db_path=app.state.db_path)

    @app.post("/api/mail/sync")
    def post_mail_sync():
        try:
            return sync_replies(app.state.db_path)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/followups")
    def get_followups(status: str | None = None, limit: int = 100):
        return list_followups(status=status, limit=limit, db_path=app.state.db_path)

    @app.post("/api/followups/process")
    def post_followups_process(send: bool = False):
        try:
            return process_due_followups(db_path=app.state.db_path, send=send)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()
