"""Company statements (docs/PHASE6_API_CONTRACT.md, package D): Schedule III classification, Balance Sheet and Statement of Profit and Loss with notes and previous-year comparatives."""

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut
from app.api.schemas_final_sch3 import ClassificationIn
from app.services import final_sch3
from app.services.final_sch3 import ClassificationRow, UnclassifiedError

router = APIRouter(tags=["final-accounts"])


def _unclassified(exc: UnclassifiedError) -> JSONResponse:
    """F-44: 422 with the findings; the statement is returned too so the screen can still show what it can."""
    error = exc.error
    return JSONResponse(status_code=422, content={"code": error.code, "message": error.message,
                                                  "details": {**error.details, "statement": exc.statement}})


@router.get("/clients/{client_id}/final/sch3/classification")
def get_classification(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return final_sch3.get_classification(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))


@router.put("/clients/{client_id}/final/sch3/classification", response_model=OkOut)
def put_classification(client_id: str, body: ClassificationIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    rows = [ClassificationRow(r.ledger_id, r.line_code, r.cf_class, r.note) for r in body.rows]
    final_sch3.put_classification(conn, parse_id(client_id, "Client"), rows, actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/final/sch3/balance-sheet")
def sch3_balance_sheet(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    try:
        return final_sch3.balance_sheet(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), as_on)
    except UnclassifiedError as exc:
        return _unclassified(exc)


@router.get("/clients/{client_id}/final/sch3/profit-loss")
def sch3_profit_loss(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    try:
        return final_sch3.profit_loss(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))
    except UnclassifiedError as exc:
        return _unclassified(exc)


@router.get("/clients/{client_id}/final/sch3/notes")
def sch3_notes(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    try:
        return final_sch3.notes(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))
    except UnclassifiedError as exc:
        return _unclassified(exc)
