from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from .commercial_lifecycle import commercial_metrics, get_commercial_opportunity, set_commercial_status
from .pilot_proposal import generate_pilot_proposal


class CommercialStatusUpdate(BaseModel):
    status: str = Field(min_length=3, max_length=40)
    lost_reason: str | None = Field(default=None, max_length=1000)
    pilot_price_clp: int | None = Field(default=None, ge=0)
    monthly_price_clp: int | None = Field(default=None, ge=0)
    expected_value_clp: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=3000)


def register_commercial_routes(app):
    @app.get("/api/commercial/metrics")
    def get_commercial_metrics():
        return commercial_metrics(app.state.db_path)

    @app.get("/api/cases/{case_id}/commercial")
    def get_case_commercial(case_id: int):
        try:
            return get_commercial_opportunity(case_id, app.state.db_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/cases/{case_id}/commercial")
    def patch_case_commercial(case_id: int, payload: CommercialStatusUpdate):
        try:
            return set_commercial_status(
                case_id,
                payload.status,
                lost_reason=payload.lost_reason,
                pilot_price_clp=payload.pilot_price_clp,
                monthly_price_clp=payload.monthly_price_clp,
                expected_value_clp=payload.expected_value_clp,
                note=payload.note,
                db_path=app.state.db_path,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/cases/{case_id}/pilot-proposal")
    def get_case_pilot_proposal(
        case_id: int,
        cases_limit: int = Query(default=5, ge=1, le=20),
        pilot_days: int = Query(default=30, ge=7, le=90),
        price_clp: int | None = Query(default=None, ge=0),
    ):
        try:
            return generate_pilot_proposal(
                case_id,
                cases_limit=cases_limit,
                pilot_days=pilot_days,
                price_clp=price_clp,
                db_path=app.state.db_path,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
