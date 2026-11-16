import dataclasses
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
from app.api.schemas_tds_deduction import tds_from_body
from app.db.repositories import VoucherRecord
from app.engine.inventory_voucher import StockLineIn
from app.engine.models import Allocation, ValidationError, VoucherDraft, VoucherLine
from app.services import (
    gst_hooks,
    inventory_hooks,
    inventory_movements,
    queries,
    tds_hooks,
    vouchers,
)

router = APIRouter(tags=["vouchers"])


def draft_from_body(client_id: uuid.UUID, body: VoucherIn) -> tuple[VoucherDraft | None, list[ValidationError]]:
    """The draft of a request body, or the G-14 / G-17 (invoice block) and T-05 / T-16 (TDS block) errors."""
    tds, tds_errors = tds_from_body(body.tds)
    if tds_errors:
        return None, tds_errors
    if body.gst is None:
        return dataclasses.replace(_draft(client_id, body), tds=tds), []
    invoice, party_allocations, errors = invoice_from_body(body)
    if errors:
        return None, errors
    return VoucherDraft(
        client_id, body.voucher_type, body.voucher_date, body.narration, body.reference_no, body.party_ledger_id, (),
        body.duplicate_override_reason, body.goods_received_date, invoice, None, party_allocations, tds,
        tuple(
            StockLineIn(n, None if x.stock.godown_id is None else str(x.stock.godown_id),
                        None if x.stock.original_movement_id is None else str(x.stock.original_movement_id))
            for n, x in enumerate(body.gst.items, start=1) if x.stock is not None
        ),
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


def _voucher_out(r: VoucherRecord, gst: dict | None = None, tds: dict | None = None) -> VoucherOut:
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
        gst=gst, tds=tds,
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
    gst = gst_hooks.load_invoice(conn, record.client_id, record.id)
    if gst is not None:  # Phase 5: the stock effect of each item line (null when the line moves no stock)
        stock = {s["item_line_no"]: {k: v for k, v in s.items() if k != "item_line_no"}
                 for s in inventory_hooks.load_stock(conn, record.client_id, record.id) or []}
        for item in gst["items"]:
            item["stock"] = stock.get(item["item_line_no"])
    return _voucher_out(record, gst, tds_hooks.load_tds(conn, record.client_id, record.id))


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


# ======================================================================================== Phase 5: stock


def _issue(e, severity: str) -> dict:
    return {"rule_id": e.rule_id, "message": e.message, "line_no": e.line_no, "severity": severity}


@router.post("/clients/{client_id}/vouchers/stock-preview")
def stock_preview(client_id: str, body: VoucherIn, conn: Connection = Depends(get_conn)):
    """The stock movements this invoice would make, S-01 over the whole chronology, stock after the voucher. Nothing is saved."""
    draft, bad = draft_from_body(parse_id(client_id, "Client"), body)
    if draft is not None and body.gst is not None:
        draft, bad = gst_hooks.expand_invoice(conn, draft)
    if bad or draft is None or body.gst is None:
        errors = bad or [ValidationError("G-14", "The stock preview needs the invoice block (gst).")]
        return {"movements": [], "stock_after": [], "errors": [_issue(e, "error") for e in errors], "warnings": []}
    check = inventory_movements.preview(conn, draft)
    return {
        "movements": [
            {"item_id": m["item_id"], "godown_id": m["godown_id"], "kind": m["kind"], "quantity": f"{m['quantity']:.3f}",
             "cost": None if m["cost"] is None else money(m["cost"]), "item_line_no": m["item_line_no"]}
            for m in check.movements
        ],
        "stock_after": [{**s, "quantity": f"{s['quantity']:.3f}"} for s in check.stock_after],
        "errors": [_issue(e, "error") for e in check.errors],
        "warnings": [_issue(e, "warning") for e in check.warnings],
    }


@router.get("/clients/{client_id}/stock-items/{item_id}/returnable")
def returnable(client_id: str, item_id: str, on: date | None = None, conn: Connection = Depends(get_conn)):
    """Sales and purchases of an item that a Credit / Debit Note can name as `original_movement_id`."""
    rows = inventory_movements.returnable(conn, parse_id(client_id, "Client"), parse_id(item_id, "Item"), on)
    return [{**r, "movement_id": str(r["movement_id"]), "quantity": f"{r['quantity']:.3f}",
             "already_returned": f"{r['already_returned']:.3f}", "returnable": f"{r['returnable']:.3f}"} for r in rows]
