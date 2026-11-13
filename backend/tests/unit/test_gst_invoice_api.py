"""API input of invoice mode: G-14 (typed lines / tax amounts refused) and G-17 (unreadable numbers), no database."""

from datetime import date
from decimal import Decimal as D

from app.api.gst_invoice_input import invoice_from_body
from app.api.schemas import VoucherIn

LEDGER = "11111111-1111-1111-1111-111111111111"
REG = "22222222-2222-2222-2222-222222222222"


def body(item_extra=None, lines=None, quantity="2", rate="100.00"):
    item = {"description": "Item", "hsn_sac": "8415", "uqc": "nos", "quantity": quantity, "unit_rate": rate, "ledger_id": LEDGER}
    item.update(item_extra or {})
    return VoucherIn.model_validate({
        "voucher_type": "sales", "voucher_date": "2026-04-05", "narration": "x", "lines": lines or [],
        "gst": {"gst_registration_id": REG, "document_kind": "tax_invoice", "supply_category": "b2b",
                "place_of_supply": "29", "invoice_date": "2026-04-05", "counterparty_gstin": " 29abcde1234f1zw ", "items": [item]},
    })


def test_G14_valid_block_becomes_invoice_in_with_exact_decimals():
    invoice, allocations, errors = invoice_from_body(body())
    assert errors == [] and allocations == ()
    assert (invoice.place_of_supply, invoice.invoice_date, invoice.counterparty_gstin) == ("29", date(2026, 4, 5), "29ABCDE1234F1ZW")
    item = invoice.items[0]
    assert (item.quantity, item.unit_rate, item.discount, item.uqc) == (D(2), D("100.00"), D("0.00"), "NOS")


def test_G14_typed_tax_amount_on_an_item_is_refused():
    _, _, errors = invoice_from_body(body({"cgst": "9.00", "gst_rate": "18"}))
    assert [(e.rule_id, e.line_no) for e in errors] == [("G-14", 1)]


def test_G14_typed_ledger_lines_are_refused_in_invoice_mode():
    _, _, errors = invoice_from_body(body(lines=[{"ledger_id": LEDGER, "debit": "1.00"}]))
    assert [e.rule_id for e in errors] == ["G-14"]


def test_G17_unreadable_quantity_or_rate_is_refused_with_the_item_number():
    _, _, errors = invoice_from_body(body(quantity="two", rate="1,000"))
    assert [(e.rule_id, e.line_no) for e in errors] == [("G-17", 1), ("G-17", 1)]
