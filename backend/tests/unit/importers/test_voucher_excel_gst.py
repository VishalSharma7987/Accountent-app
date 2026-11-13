"""Invoice-mode columns of the Excel voucher import (Phase 3, package B). Pure parsing, no database."""

from datetime import date
from decimal import Decimal as D

from xlsx_helpers import make_xlsx

from app.importers.voucher_excel import COLUMNS, GST_COLUMNS, parse_workbook

HEADER = COLUMNS + GST_COLUMNS


def row(ref="S1", **gst):
    base = {name: None for name in HEADER}
    base.update({"ref_id": ref, "date": "2026-04-05", "voucher_type": "sales", "narration": "Sale", "party_ledger": "Rahul"})
    base.update(gst)
    return [base[name] for name in HEADER]


ITEM = {"gst_registration": "27ABCDE1234F1Z0", "document_kind": "tax_invoice", "supply_category": "b2b",
        "place_of_supply": "29", "item_description": "AC", "hsn_sac": "8415", "uqc": "NOS", "quantity": 2,
        "unit_rate": "10,000.50", "discount": "0", "item_ledger": "Sales", "counterparty_gstin": "29ABCDE1234F1ZW"}


def test_G14_import_invoice_rows_form_one_voucher_with_items():
    rows = [row(**ITEM), row(**{**ITEM, "item_description": "Fan", "hsn_sac": "8414", "quantity": 1, "unit_rate": "500", "item_ledger": "Sales",
                                "gst_registration": None, "document_kind": None, "supply_category": None, "place_of_supply": None,
                                "counterparty_gstin": None, "uqc": None, "discount": None})]
    voucher = parse_workbook(make_xlsx(rows, header=HEADER)).vouchers[0]
    assert voucher.errors == [] and voucher.lines == []
    g = voucher.gst
    assert (g.registration, g.document_kind, g.supply_category, g.place_of_supply, g.counterparty_gstin) == (
        "27ABCDE1234F1Z0", "tax_invoice", "b2b", "29", "29ABCDE1234F1ZW")
    assert [(i.row, i.description, i.hsn_sac, i.uqc, i.quantity, i.unit_rate, i.discount, i.item_ledger) for i in voucher.items] == [
        (2, "AC", "8415", "NOS", D(2), "10000.50", "0", "Sales"),
        (3, "Fan", "8414", None, D(1), "500", None, "Sales"),
    ]
    assert voucher.voucher_date == date(2026, 4, 5)


def test_G14_tax_columns_in_the_sheet_are_refused():
    header = HEADER + ("cgst",)
    data = make_xlsx([[*row(**ITEM), "90.00"]], header=header)
    voucher = parse_workbook(data).vouchers[0]
    assert any("G-14" in e.message and e.row == 2 for e in voucher.errors)


def test_G14_import_cannot_mix_item_rows_and_ledger_rows_in_one_voucher():
    rows = [row(**ITEM), row(ledger_name="Sales", credit="100.00")]
    voucher = parse_workbook(make_xlsx(rows, header=HEADER)).vouchers[0]
    assert any("mix" in e.message for e in voucher.errors)


def test_G14_import_a_later_row_cannot_change_the_invoice_header():
    rows = [row(**ITEM), row(**{**ITEM, "place_of_supply": "27"})]
    voucher = parse_workbook(make_xlsx(rows, header=HEADER)).vouchers[0]
    assert any("place_of_supply" in e.message and e.row == 3 for e in voucher.errors)


def test_G14_import_plain_files_without_gst_columns_still_parse():
    voucher = parse_workbook(make_xlsx([["P1", "2026-04-05", "payment", "Rent", 10, None, "x", None, None, None, None, None, None]])).vouchers[0]
    assert voucher.gst is None and voucher.items == []
