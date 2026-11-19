"""Final statements (docs/PHASE6_API_CONTRACT.md, package C): closing stock approval, Trading A/c, Profit and Loss, Balance Sheet,
Appropriation account and the ledger positions behind them (drill-down target)."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas_final_statements import ClosingStockIn
from app.services import final_closing_stock, final_statements

router = APIRouter(tags=["final-accounts"])


def _ids(client_id: str, financial_year_id: str):
    return parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year")


@router.get("/clients/{client_id}/final/closing-stock")
def get_closing_stock(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return final_closing_stock.get_closing_stock(conn, *_ids(client_id, financial_year_id))


@router.put("/clients/{client_id}/final/closing-stock/{financial_year_id}")
def put_closing_stock(client_id: str, financial_year_id: str, body: ClosingStockIn, conn: Connection = Depends(get_conn),
                      actor: str = Depends(get_actor)):
    return final_closing_stock.approve_closing_stock(
        conn, *_ids(client_id, financial_year_id), source=body.source, as_on_date=body.as_on_date, cost_value=body.cost_value,
        write_down=body.write_down, basis_note=body.basis_note, actor=actor)


@router.get("/clients/{client_id}/final/trading")
def get_trading(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    return final_statements.trading(conn, *_ids(client_id, financial_year_id), as_on)


@router.get("/clients/{client_id}/final/profit-loss")
def get_profit_loss(client_id: str, financial_year_id: str, as_on: date | None = None, format: str | None = None,
                    conn: Connection = Depends(get_conn)):
    return final_statements.profit_loss(conn, *_ids(client_id, financial_year_id), as_on, format)


@router.get("/clients/{client_id}/final/balance-sheet")
def get_balance_sheet(client_id: str, financial_year_id: str, as_on: date | None = None, format: str | None = None,
                      conn: Connection = Depends(get_conn)):
    return final_statements.balance_sheet(conn, *_ids(client_id, financial_year_id), as_on, format)


@router.get("/clients/{client_id}/final/appropriation")
def get_appropriation(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return final_statements.appropriation(conn, *_ids(client_id, financial_year_id))


@router.get("/clients/{client_id}/final/ledger-positions")
def get_ledger_positions(client_id: str, financial_year_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    return final_statements.ledger_positions_out(conn, *_ids(client_id, financial_year_id), as_on)
