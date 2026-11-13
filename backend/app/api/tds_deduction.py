"""TDS / TCS deduction on vouchers: tds-preview, register, threshold position (Phase 4, package B).

Contract: docs/PHASE4_API_CONTRACT.md "Deduction on vouchers". The `tds` block itself travels on the ordinary voucher
endpoints (api/vouchers.py).
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.api.deps import get_conn, parse_id
from app.api.errors import rule_errors_body, rule_errors_response
from app.api.schemas import VoucherIn, money
from app.api.vouchers import draft_from_body
from app.db import repositories_tds_deduction as tdb
from app.engine.models import VoucherDraft
from app.engine.money import MoneyError, parse_amount
from app.services import tds_deduction, tds_hooks, vouchers

router = APIRouter(tags=["tds"])


def _lines_out(conn: Connection, draft: VoucherDraft) -> list[dict]:
    names = tdb.ledger_names(conn, [x.ledger_id for x in draft.lines])
    out = []
    for n, x in enumerate(draft.lines, start=1):
        try:
            debit, credit = (money(parse_amount(v)) if v not in (None, "") else "0.00" for v in (x.debit, x.credit))
        except MoneyError:  # unreadable amounts are reported by the rule errors (V-03)
            debit, credit = str(x.debit or ""), str(x.credit or "")
        out.append({"line_no": n, "ledger_id": str(x.ledger_id), "ledger_name": names.get(x.ledger_id, ""), "debit": debit, "credit": credit})
    return out


@router.post("/clients/{client_id}/vouchers/tds-preview")
def tds_preview(client_id: str, body: VoucherIn, conn: Connection = Depends(get_conn)):
    """The lines and tax working of a voucher as it would be saved. Nothing is written; 200 even when rules fail."""
    draft, bad = draft_from_body(parse_id(client_id, "Client"), body)
    if bad:
        return {"lines": [], "tds": None, **rule_errors_body(bad)}
    expanded, errors = tds_hooks.expand_tds(conn, draft)
    if not errors:
        errors = vouchers.validate_draft(conn, expanded)  # an expanded draft is not expanded twice
    return {
        "lines": _lines_out(conn, expanded), "tds": tds_deduction.preview_block(conn, expanded), **rule_errors_body(errors),
    }


@router.get("/clients/{client_id}/tds/register")
def tds_register(
    client_id: str, financial_year_id: str | None = None, quarter: int | None = None, nature_key: str | None = None,
    deductee_ledger_id: str | None = None, deposit_status: str = "all", conn: Connection = Depends(get_conn),
):
    return tds_deduction.register(
        conn, parse_id(client_id, "Client"),
        financial_year_id=parse_id(financial_year_id, "Financial year") if financial_year_id else None,
        quarter=quarter, nature_key=nature_key,
        deductee_ledger_id=parse_id(deductee_ledger_id, "Deductee") if deductee_ledger_id else None,
        deposit_status=deposit_status,
    )


@router.get("/clients/{client_id}/tds/register/by-deductee")
def tds_register_by_deductee(client_id: str, financial_year_id: str, conn: Connection = Depends(get_conn)):
    return tds_deduction.by_deductee(conn, parse_id(client_id, "Client"), parse_id(financial_year_id, "Financial year"))


@router.get("/clients/{client_id}/tds/threshold-position")
def tds_threshold_position(client_id: str, deductee_ledger_id: str, nature_key: str, on: date | None = None, conn: Connection = Depends(get_conn)):
    result = tds_deduction.threshold_position(
        conn, parse_id(client_id, "Client"), parse_id(deductee_ledger_id, "Deductee"), nature_key, on or date.today()
    )
    return rule_errors_response(result) if isinstance(result, list) else result

