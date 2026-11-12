from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.schemas import (
    StatementOut,
    StatementRowOut,
    TrialBalanceOut,
    TrialBalanceRowOut,
    TrialBalanceSectionOut,
    balance_out,
    money,
)
from app.services import reports

router = APIRouter(tags=["reports"])


@router.get("/clients/{client_id}/reports/ledger-statement", response_model=StatementOut)
def ledger_statement(
    client_id: str,
    ledger_id: str,
    from_: date = Query(alias="from"),
    to: date = Query(),
    conn: Connection = Depends(get_conn),
):
    s = reports.ledger_statement(conn, parse_id(client_id, "Client"), parse_id(ledger_id, "Ledger"), from_, to)
    return StatementOut(
        ledger_id=s.ledger_id, ledger_name=s.ledger_name, from_date=s.from_date, to_date=s.to_date,
        opening=balance_out(s.opening), closing=balance_out(s.closing),
        total_debit=money(s.total_debit), total_credit=money(s.total_credit),
        rows=[
            StatementRowOut(
                kind=r.kind, date=r.date, voucher_number=r.voucher_number, voucher_type=r.voucher_type,
                narration=r.narration, particulars=r.particulars, debit=money(r.debit), credit=money(r.credit),
                balance=balance_out(r.balance),
            )
            for r in s.rows
        ],
    )


@router.get("/clients/{client_id}/reports/trial-balance", response_model=TrialBalanceOut)
def trial_balance(client_id: str, as_on: date, hide_zero: bool = False, conn: Connection = Depends(get_conn)):
    t = reports.trial_balance(conn, parse_id(client_id, "Client"), as_on, hide_zero=hide_zero)
    return TrialBalanceOut(
        as_on=t.as_on,
        sections=[
            TrialBalanceSectionOut(
                group_code=s.group_code, group_name=s.group_name, debit=money(s.debit), credit=money(s.credit),
                rows=[
                    TrialBalanceRowOut(group_path=list(r.group_path), ledger_id=r.ledger_id,
                                       ledger_name=r.ledger_name, debit=money(r.debit), credit=money(r.credit))
                    for r in s.rows
                ],
            )
            for s in t.sections
        ],
        total_debit=money(t.total_debit), total_credit=money(t.total_credit),
        difference=balance_out(t.difference), is_balanced=t.is_balanced,
    )
