"""Request and response models for 26AS / AIS import and reconciliation (Phase 4, package E). Amounts are 2-decimal strings."""

from pydantic import BaseModel

from app.api.schemas import money
from app.engine.tds_recon import BookEntry, ReconRow, Row26
from app.services.tds_recon import ImportResult, Reconciliation


class LinkIn(BaseModel):
    row_id: str
    item_id: str | None = None
    voucher_id: str | None = None
    link_kind: str
    note: str


def import_out(r: ImportResult) -> dict:
    return {"import_id": str(r.import_id), "rows": r.row_count, "totals": {k: money(v) for k, v in r.totals.items()}}


def import_row_out(i: dict) -> dict:
    return {"id": str(i["id"]), "financial_year_id": str(i["financial_year_id"]), "source": i["source"], "side": i["side"],
            "file_name": i["file_name"], "row_count": i["row_count"], "imported_by": i["imported_by"],
            "imported_at": i["imported_at"].isoformat()}


def statement_row_out(r: dict) -> dict:
    return {
        "id": str(r["id"]), "row_no": r["row_no"], "deductor_tan": r["deductor_tan"], "deductor_name": r["deductor_name"],
        "deductee_pan": r["deductee_pan"], "section_ref": r["section_ref"],
        "transaction_date": r["transaction_date"].isoformat() if r["transaction_date"] else None,
        "booking_date": r["booking_date"].isoformat() if r["booking_date"] else None, "booking_status": r["booking_status"],
        "amount_paid": money(r["amount_paid"]), "tax_deducted": money(r["tax_deducted"]), "tax_deposited": money(r["tax_deposited"]),
    }


def _row26(r: Row26 | None) -> dict | None:
    if r is None:
        return None
    return {"row_id": str(r.row_id), "row_no": r.row_no, "deductor_tan": r.deductor_tan, "deductor_name": r.deductor_name,
            "deductee_pan": r.deductee_pan, "section_ref": r.section_ref,
            "transaction_date": r.transaction_date.isoformat() if r.transaction_date else None,
            "amount_paid": money(r.amount_paid), "tax_deducted": money(r.tax_deducted), "tax_deposited": money(r.tax_deposited)}


def _book(b: BookEntry | None, side: str) -> dict | None:
    if b is None:
        return None
    body = {"voucher_id": str(b.voucher_id) if b.voucher_id else None, "voucher_number": b.voucher_number,
            "event_date": b.event_date.isoformat(), "event_date_label": b.event_date.strftime("%d-%m-%Y"), "tds_amount": money(b.tds_amount)}
    if side == "deductor":
        body |= {"item_id": str(b.book_id), "deductee_name": b.deductee_name, "pan": b.pan, "nature_key": b.nature_key,
                 "section_ref": b.section_ref, "payment_amount": money(b.payment_amount)}
    return body


def _row(r: ReconRow, side: str) -> dict:
    return {
        "class": r.cls, "row": _row26(r.row), "books": _book(r.book, side),
        "difference": None if r.difference is None else money(r.difference),
        "paid_difference": None if r.paid_difference is None else money(r.paid_difference),
        "section_mapping_status": r.section_mapping_status, "reason": r.reason,
        "link_id": None if r.link_id is None else str(r.link_id), "link_kind": r.link_kind, "link_stale": r.link_stale,
    }


def reconciliation_out(rec: Reconciliation) -> dict:
    return {
        "import_id": str(rec.import_id), "side": rec.side, "tolerance": money(rec.tolerance), "summary": rec.result.summary,
        "rows": [_row(r, rec.side) for r in rec.result.rows], "rule_status": rec.rule_status,
    }
