"""Turns the `gst` block of a voucher request into the engine's InvoiceIn (Phase 3, package B).

Refuses typed ledger lines and tax amounts (G-14) and unreadable quantities / rates (G-17) with rule errors.
"""

import re
from decimal import Decimal

from app.engine.gst_invoice import typed_tax_errors
from app.engine.gst_types import InvoiceIn, ItemLineIn
from app.engine.models import Allocation, ValidationError

NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _decimal(text: str | None, label: str, n: int, errors: list[ValidationError]) -> Decimal:
    shown = "" if text is None else str(text).strip()
    if not NUMBER.match(shown):
        errors.append(ValidationError("G-17", f"Item {n}: {label} '{shown}' is not a valid number.", n))
        return Decimal(0)
    return Decimal(shown)


def invoice_from_body(body) -> tuple[InvoiceIn | None, tuple[Allocation, ...], list[ValidationError]]:
    gst = body.gst
    errors = typed_tax_errors(bool(body.lines), [list((item.model_extra or {}).keys()) for item in gst.items])
    items = []
    for n, item in enumerate(gst.items, start=1):
        items.append(ItemLineIn(
            item.description, item.hsn_sac.strip(), _decimal(item.quantity, "quantity", n, errors),
            _decimal(item.unit_rate, "rate", n, errors), _decimal(item.discount, "discount", n, errors), item.ledger_id,
            item.item_id, (item.uqc or "").strip().upper() or None, item.rcm_category_key or None,
            item.itc_category_key or None, item.itc_exception_claimed, item.itc_exception_note,
        ))
    if errors:
        return None, (), errors
    invoice = InvoiceIn(
        str(gst.gst_registration_id), gst.document_kind, gst.supply_category, gst.place_of_supply.strip(), gst.invoice_date,
        tuple(items), (gst.counterparty_gstin or "").strip().upper() or None, gst.original_invoice_no,
        gst.original_invoice_date, gst.note_reason,
    )
    allocations = tuple(Allocation(a.kind, a.amount, a.bill_ref, a.due_date) for a in gst.allocations)
    return invoice, allocations, []
