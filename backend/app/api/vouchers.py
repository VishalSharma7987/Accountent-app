import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Connection

from app.api.deps import get_actor, get_conn, parse_id
from app.api.errors import rule_errors_response
from app.api.gst_invoice_input import invoice_from_body
from app.api.schemas import (
    AllocationOut,
    OkOut,
    PostedOut,
    ReversedOut,
    ReverseIn,
    VoucherCreated,
    VoucherIn,
    VoucherLineOut,
    VoucherList,
    VoucherOut,
    VoucherStatus,
    VoucherSummary,
    VoucherType,
    money,
)
from app.db.repositories import VoucherRecord
from app.engine.models import Allocation, ValidationError, VoucherDraft, VoucherLine
from app.services import gst_hooks, queries, vouchers

router = APIRouter(tags=["vouchers"])


def draft_from_body(client_id: uuid.UUID, body: VoucherIn) -> tuple[VoucherDraft | None, list[ValidationError]]:
    """The draft of a request body, or the G-14 / G-17 errors of its invoice block (Phase 3)."""
    if body.gst is None:
        return _draft(client_id, body), []
    invoice, party_allocations, errors = invoice_from_body(body)
    if errors:
        return None, errors
    return VoucherDraft(
        client_id, body.voucher_type, body.voucher_date, body.narration, body.reference_no, body.party_ledger_id, (),
        body.duplicate_override_reason, body.goods_received_date, invoice, None, party_allocations,
    ), []


def _draft(client_id: uuid.UUID, body: VoucherIn) -> VoucherDraft:
    return VoucherDraft(
        client_id, body.voucher_type, body.voucher_date, body.narration, body.reference_no, body.party_ledger_id,
        tuple(
            VoucherLine(x.ledger_id, x.debit, x.credit,
                        tuple(Allocation(a.kind, a.amount, a.bill_ref, a.due_date) for a in x.allocations))
            for x in body.lines
        ),
        body.duplicate_override_reason, body.goods_received_date,
    )


def _voucher_out(r: VoucherRecord, gst: dict | None = None) -> VoucherOut:
    roles = (gst or {}).pop("line_roles", {})
    return VoucherOut(
        id=r.id, client_id=r.client_id, financial_year_id=r.financial_year_id, voucher_type=r.voucher_type,
        voucher_number=r.voucher_number, voucher_date=r.voucher_date, narration=r.narration,
        reference_no=r.reference_no, party_ledger_id=r.party_ledger_id, status=r.status,
        reverses_voucher_id=r.reverses_voucher_id, reversed_by_voucher_id=r.reversed_by_voucher_id,
        duplicate_override_reason=r.duplicate_override_reason, created_by=r.created_by,
        approved_by=r.approved_by, posted_by=r.posted_by, goods_received_date=r.goods_received_date,
        lines=[VoucherLineOut(line_no=x.line_no, ledger_id=x.ledger_id, ledger_name=x.ledger_name,
                              debit=money(x.debit), credit=money(x.credit),
                              gst_role=roles.get(x.line_no, {}).get("gst_role"),
                              item_line_no=roles.get(x.line_no, {}).get("item_line_no"),
                              allocations=[AllocationOut(kind=a.kind, amount=money(a.amount), bill_ref=a.bill_ref,
                                                         due_date=a.due_date) for a in x.allocations])
               for x in r.lines],
        gst=gst,
    )


@router.post("/clients/{client_id}/vouchers", status_code=201, response_model=VoucherCreated)
def create_voucher(client_id: str, body: VoucherIn, conn: Connection = Depends(get_conn),
                   actor: str = Depends(get_actor)):
    draft, bad = draft_from_body(parse_id(client_id, "Client"), body)
    if bad:
        return rule_errors_response(bad)
    result = vouchers.create_draft(conn, draft, actor=actor)
    if result.errors:
        return rule_errors_response(result.errors)
    return VoucherCreated(voucher_id=result.voucher_id)


@router.get("/clients/{client_id}/vouchers", response_model=VoucherList)
def list_vouchers(
    client_id: str,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    type: VoucherType | None = None,
    status: VoucherStatus | None = None,
    ledger_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    conn: Connection = Depends(get_conn),
):
    items, total = queries.list_vouchers(
        conn, parse_id(client_id, "Client"), date_from=from_, date_to=to, voucher_type=type, status=status,
        ledger_id=parse_id(ledger_id, "Ledger") if ledger_id else None, limit=limit, offset=max(0, offset),
    )
    return VoucherList(
        items=[VoucherSummary(**{**i, "total": money(i["total"])}) for i in items], total_count=total
    )


@router.get("/vouchers/{voucher_id}", response_model=VoucherOut)
def get_voucher(voucher_id: str, conn: Connection = Depends(get_conn)):
    record = vouchers.get_voucher(conn, parse_id(voucher_id, "Voucher"))
    return _voucher_out(record, gst_hooks.load_invoice(conn, record.client_id, record.id))


@router.put("/vouchers/{voucher_id}", response_model=VoucherCreated)
def update_voucher(voucher_id: str, body: VoucherIn, conn: Connection = Depends(get_conn),
                   actor: str = Depends(get_actor)):
    vid = parse_id(voucher_id, "Voucher")
    current = vouchers.get_voucher(conn, vid)
    draft, bad = draft_from_body(current.client_id, body)
    if bad:
        return rule_errors_response(bad)
    result = vouchers.update_draft(conn, vid, draft, actor=actor)
    if result.errors:
        return rule_errors_response(result.errors)
    return VoucherCreated(voucher_id=result.voucher_id)


@router.delete("/vouchers/{voucher_id}", status_code=204)
def delete_voucher(voucher_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    vouchers.delete_draft(conn, parse_id(voucher_id, "Voucher"), actor=actor)
    return Response(status_code=204)


@router.post("/vouchers/{voucher_id}/approve", response_model=OkOut)
def approve_voucher(voucher_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    vouchers.approve(conn, parse_id(voucher_id, "Voucher"), actor=actor)
    return OkOut()


@router.post("/vouchers/{voucher_id}/return-to-draft", response_model=OkOut)
def return_voucher_to_draft(voucher_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    vouchers.return_to_draft(conn, parse_id(voucher_id, "Voucher"), actor=actor)
    return OkOut()


@router.post("/vouchers/{voucher_id}/post", response_model=PostedOut)
def post_voucher(voucher_id: str, conn: Connection = Depends(get_conn), actor: str = Depends(get_actor)):
    return PostedOut(voucher_number=vouchers.post(conn, parse_id(voucher_id, "Voucher"), actor=actor))


@router.post("/vouchers/{voucher_id}/reverse", status_code=201, response_model=ReversedOut)
def reverse_voucher(voucher_id: str, body: ReverseIn, conn: Connection = Depends(get_conn),
                    actor: str = Depends(get_actor)):
    reversal = vouchers.reverse(conn, parse_id(voucher_id, "Voucher"), body.reversal_date, body.reason, actor=actor)
    return ReversedOut(reversal_voucher_id=reversal)
