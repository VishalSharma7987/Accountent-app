from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import balance_out, money
from app.api.schemas_cash import CashBookDayOut, CashBookEntryOut, CashBookOut
from app.services import cashbook

router = APIRouter(tags=["reports"])


@router.get("/clients/{client_id}/reports/cash-book", response_model=CashBookOut)
def cash_book(
    client_id: str,
    ledger_id: str,
    from_: date = Query(alias="from"),
    to: date = Query(),
    conn: Connection = Depends(get_conn),
):
    """Cash Book of a Cash-in-hand ledger or Bank Book of a Bank Accounts ledger."""
    b = cashbook.cash_book(conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), from_, to)
    return CashBookOut(
        ledger_id=b.ledger_id, ledger_name=b.ledger_name, from_date=b.from_date, to_date=b.to_date,
        opening=balance_out(b.opening), total_receipts=money(b.total_receipts), total_payments=money(b.total_payments),
        closing=balance_out(b.closing),
        days=[
            CashBookDayOut(
                date=d.date, receipts=money(d.receipts), payments=money(d.payments), closing=balance_out(d.closing),
                entries=[
                    CashBookEntryOut(
                        voucher_id=e.voucher_id, voucher_number=e.voucher_number, voucher_type=e.voucher_type,
                        narration=e.narration, counter_ledgers=list(e.counter_ledgers),
                        receipt=money(e.receipt), payment=money(e.payment),
                    )
                    for e in d.entries
                ],
            )
            for d in b.days
        ],
    )
