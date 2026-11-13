"""Request and response models for GSTR-2B import and reconciliation (Phase 3, package D). Amounts are 2-decimal strings."""

from decimal import Decimal

from pydantic import BaseModel

from app.api.schemas import money
from app.engine.gst_recon import HEADS, BookDoc, Doc2B, ReconRow
from app.services.gst_recon import Reconciliation


class LinkIn(BaseModel):
    document_id: str
    voucher_id: str
    link_kind: str
    note: str


def _heads(item) -> dict:
    return {h: money(getattr(item, h)) for h in HEADS if h != "taxable_value"} | {"taxable_value": money(item.taxable_value)}


def _book(b: BookDoc | None) -> dict | None:
    if b is None:
        return None
    return {"voucher_id": str(b.voucher_id), "voucher_number": b.voucher_number, "supplier_gstin": b.supplier_gstin,
            "supplier_invoice_no": b.doc_no, "invoice_date": b.doc_date.isoformat(), **_heads(b), "itc_status": b.itc_status}


def _doc(d: Doc2B | None) -> dict | None:
    if d is None:
        return None
    return {"document_id": str(d.document_id), "supplier_gstin": d.supplier_gstin, "doc_no": d.doc_no,
            "doc_date": d.doc_date.isoformat(), **_heads(d), "itc_available": d.itc_available, "ims_status": d.ims_status}


def _row(r: ReconRow) -> dict:
    return {
        "class": r.cls, "books": _book(r.book), "doc_2b": _doc(r.doc),
        "differences": [{"field": d.field, "books": money(d.books), "doc_2b": money(d.doc_2b), "difference": money(d.difference)}
                        for d in r.differences],
        "note": r.note, "link_id": None if r.link_id is None else str(r.link_id),
    }


def _money_dict(values: dict[str, Decimal]) -> dict:
    return {k: money(v) for k, v in values.items()}


def reconciliation_out(recon: Reconciliation) -> dict:
    result = recon.result
    return {
        "period": recon.period.strftime("%Y-%m"), "tolerance": money(recon.tolerance), "summary": result.summary,
        "rows": [_row(r) for r in result.rows],
        "totals": {k: _money_dict(v) for k, v in result.totals.items()},
    }


def import_out(r) -> dict:
    return {"import_id": str(r.import_id), "documents": r.document_count, "period": r.period.strftime("%Y-%m"),
            "generated_on": None if r.generated_on is None else r.generated_on.isoformat(),
            "totals": {k: money(v) for k, v in r.totals.items()}}


def import_row_out(r: dict) -> dict:
    return {"id": str(r["id"]), "kind": r["kind"], "period": r["return_period"].strftime("%Y-%m"), "file_name": r["file_name"],
            "generated_on": None if r["generated_on"] is None else r["generated_on"].isoformat(),
            "document_count": r["document_count"], "created_at": r["created_at"].isoformat(),
            "registration_id": str(r["gst_registration_id"])}


def document_out(d: dict) -> dict:
    return {
        "id": str(d["id"]), "section": d["section"], "supplier_gstin": d["supplier_gstin"], "supplier_name": d["supplier_name"],
        "doc_type": d["doc_type"], "doc_no": d["doc_no"], "doc_date": d["doc_date"].isoformat(),
        **{h: money(d[h]) for h in HEADS}, "itc_available": d["itc_available"], "itc_reason": d["itc_reason"],
        "ims_status": d["ims_status"],
        "supplier_return_period": None if d["supplier_return_period"] is None else d["supplier_return_period"].isoformat(),
    }


def apply_out(r: dict) -> dict:
    return {
        "updated": [{k: (str(v) if k == "itc_entry_id" else v) for k, v in u.items()} for u in r["updated"]],
        "applied": r["applied"],
        "effects": [{"voucher_id": str(e.voucher_id), "supplier_tax_paid": e.supplier_tax_paid,
                     "pending_reason": e.pending_reason, "note": e.note} for e in r["effects"]],
    }
