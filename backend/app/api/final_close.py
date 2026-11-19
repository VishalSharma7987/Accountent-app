"""Year-end close and reopen (docs/PHASE6_API_CONTRACT.md, package F)."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_final_close import CloseIn, ReopenIn
from app.services import final_close

router = APIRouter(tags=["final-accounts"])


@router.get("/clients/{client_id}/final/close/check")
def get_check(client_id: str, financial_year_id: str, create_next_year: bool = False, confirm_no_depreciation: bool = False,
              conn: Connection = Depends(get_conn)):
    return final_close.check(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), create_next_year=create_next_year,
                             confirm_no_depreciation=confirm_no_depreciation)


@router.post("/clients/{client_id}/final/close", status_code=201)
def post_close(client_id: str, body: CloseIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return final_close.close(conn, parse_id(client_id, "Client"), parse_id(body.financial_year_id, "Financial year"),
                             create_next_year=body.create_next_year, confirm_no_depreciation=body.confirm_no_depreciation,
                             acknowledged_flags=body.acknowledged_flags, actor=actor)


@router.get("/clients/{client_id}/final/close")
def get_close(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return final_close.get_close(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))


@router.post("/clients/{client_id}/final/close/{close_id}/reopen")
def post_reopen(client_id: str, close_id: str, body: ReopenIn, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return final_close.reopen(conn, parse_id(client_id, "Client"), parse_id(close_id, "Year-end close"), body.reason, actor=actor)
