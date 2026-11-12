from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import (
    LedgerCreate,
    LedgerCreated,
    LedgerOut,
    OkOut,
    OpeningBalancesOut,
    OpeningIn,
    OpeningRowOut,
    balance_out,
    money,
)
from app.services import client_setup, queries

router = APIRouter(tags=["ledgers"])


@router.get("/clients/{client_id}/ledgers", response_model=list[LedgerOut])
def list_ledgers(client_id: str, as_on: date | None = None, conn: Connection = Depends(get_conn)):
    rows = queries.ledgers_with_balance(conn, parse_id(client_id, "Client"), as_on)
    return [
        LedgerOut(id=x.id, name=x.name, group_code=x.group_code, group_name=x.group_name,
                  group_path=list(x.group_path), is_active=x.is_active, balance=balance_out(x.balance))
        for x in rows
    ]


@router.post("/clients/{client_id}/ledgers", status_code=201, response_model=LedgerCreated)
def create_ledger(client_id: str, body: LedgerCreate, conn: Connection = Depends(get_conn),
                  actor: str = Depends(get_actor)):
    ledger_id = client_setup.add_ledger(conn, parse_id(client_id, "Client"), body.name, body.group_code, actor=actor)
    return LedgerCreated(ledger_id=ledger_id)


@router.post("/clients/{client_id}/ledgers/{ledger_id}/deactivate", response_model=OkOut)
def deactivate_ledger(client_id: str, ledger_id: str, conn: Connection = Depends(get_conn),
                      actor: str = Depends(get_actor)):
    client_setup.deactivate_ledger(conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), actor=actor)
    return OkOut()


@router.post("/clients/{client_id}/ledgers/{ledger_id}/reactivate", response_model=OkOut)
def reactivate_ledger(client_id: str, ledger_id: str, conn: Connection = Depends(get_conn),
                      actor: str = Depends(get_actor)):
    client_setup.reactivate_ledger(conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), actor=actor)
    return OkOut()


@router.get("/clients/{client_id}/financial-years/{fy_id}/opening-balances", response_model=OpeningBalancesOut)
def get_opening_balances(client_id: str, fy_id: str, conn: Connection = Depends(get_conn)):
    report = queries.opening_balances_report(conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"))
    check = report["check"]
    return OpeningBalancesOut(
        rows=[OpeningRowOut(ledger_id=r["ledger_id"], ledger_name=r["ledger_name"], debit=money(r["debit"]),
                            credit=money(r["credit"])) for r in report["rows"]],
        total_debit=money(check.total_debit), total_credit=money(check.total_credit),
        difference=balance_out(check.difference), is_balanced=check.is_balanced,
    )


@router.put("/clients/{client_id}/financial-years/{fy_id}/opening-balances/{ledger_id}", response_model=OkOut)
def set_opening_balance(client_id: str, fy_id: str, ledger_id: str, body: OpeningIn,
                        conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    client_setup.set_opening_balance(
        conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"), parse_id(ledger_id, "Ledger"),
        body.debit, body.credit, actor=actor,
    )
    return OkOut()
