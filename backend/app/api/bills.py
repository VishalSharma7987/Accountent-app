from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.schemas import OkOut, balance_out, money
from app.api.schemas_bills import (
    OpenBillOut,
    OpeningBillOut,
    OpeningBillsIn,
    OpeningBillsOut,
    ageing_out,
    outstanding_out,
)
from app.engine.bills import OpeningBillIn
from app.engine.models import Balance
from app.services import bills

router = APIRouter(tags=["bills"])


@router.put("/clients/{client_id}/financial-years/{fy_id}/opening-bills/{ledger_id}", response_model=OkOut)
def set_opening_bills(client_id: str, fy_id: str, ledger_id: str, body: OpeningBillsIn,
                      conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    bills.set_opening_bills(
        conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"), parse_id(ledger_id, "Ledger"),
        [OpeningBillIn(b.bill_ref, b.bill_date, b.amount, b.side, b.due_date) for b in body.bills], actor=actor,
    )
    return OkOut()


@router.get("/clients/{client_id}/financial-years/{fy_id}/opening-bills/{ledger_id}", response_model=OpeningBillsOut)
def get_opening_bills(client_id: str, fy_id: str, ledger_id: str, conn: Connection = Depends(get_conn)):
    view = bills.get_opening_bills(
        conn, parse_id(client_id, "Client"), parse_id(fy_id, "Financial year"), parse_id(ledger_id, "Ledger")
    )
    return OpeningBillsOut(
        bills=[OpeningBillOut(bill_ref=r.bill_ref, bill_date=r.bill_date, due_date=r.due_date,
                              amount=money(abs(r.amount)), side="Dr" if r.amount > 0 else "Cr") for r in view.bills],
        total=balance_out(view.check.total), ledger_opening=balance_out(view.check.ledger),
        difference=balance_out(view.check.difference), is_balanced=view.check.is_balanced,
    )


@router.get("/clients/{client_id}/open-bills", response_model=list[OpenBillOut])
def open_bills(client_id: str, as_on: date, party_ledger_id: str | None = None, conn: Connection = Depends(get_conn)):
    items = bills.open_bills(
        conn, parse_id(client_id, "Client"), as_on,
        parse_id(party_ledger_id, "Party") if party_ledger_id else None,
    )
    return [
        OpenBillOut(
            party_ledger_id=b.party_ledger_id, party_name=b.party_name, bill_ref=b.bill_ref, kind=b.kind,
            bill_date=b.bill_date, due_date=b.due_date, original=balance_out(Balance.from_signed(b.original)),
            outstanding=balance_out(Balance.from_signed(b.outstanding)),
        )
        for b in items
    ]


@router.get("/clients/{client_id}/reports/outstanding")
def outstanding(client_id: str, kind: str, as_on: date, conn: Connection = Depends(get_conn)):
    return outstanding_out(bills.outstanding_report(conn, parse_id(client_id, "Client"), kind, as_on))


@router.get("/clients/{client_id}/reports/ageing")
def ageing(client_id: str, kind: str, as_on: date, conn: Connection = Depends(get_conn)):
    return ageing_out(bills.ageing_report(conn, parse_id(client_id, "Client"), kind, as_on))
