"""Cash Flow Statement, AS 3 indirect method (docs/PHASE6_API_CONTRACT.md, package E)."""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.services import final_cashflow

router = APIRouter(tags=["final-accounts"])


@router.get("/clients/{client_id}/final/cash-flow")
def get_cash_flow(client_id: str, financial_year_id: str, required: bool = False, conn: Connection = Depends(get_conn)):
    return final_cashflow.cash_flow(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"), required)
