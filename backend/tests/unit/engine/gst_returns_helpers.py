"""Literal documents for the GSTR-1 / GSTR-3B / tie-out / composition engine tests (all amounts hand-typed)."""

from datetime import date
from decimal import Decimal as D

from app.engine.gstr1 import DocRow, ItemRow

REG = "27"
X = "27AAAAA0000A1Z5"
Y = "29BBBBB1111B1Z6"


def item(taxable, rate="18", *, cgst="0", sgst="0", igst="0", cess="0", hsn="1001", qty="1", treatment="taxable",
         no=1, rcm=False, desc="Goods", uqc="NOS"):
    return ItemRow(no, hsn, desc, uqc, D(qty), D(taxable), treatment, D(rate), D(cgst), D(sgst), D(igst), D(cess), rcm)


def doc(number, vtype, cat, pos, value, items, *, gstin=None, name="", ptype=None, day=5, month=4, orig=None):
    return DocRow(
        voucher_id=number, voucher_type=vtype, number=number, invoice_date=date(2026, month, day),
        supply_category=cat, place_of_supply=pos, party_gstin=gstin, party_name=name, party_gst_type=ptype,
        invoice_value=D(value), items=tuple(items), original_invoice_no=orig,
        original_invoice_date=date(2026, 4, 5) if orig else None, note_reason="sales_return" if orig else None)


def april_docs():
    """Eight invoices and one credit note of April 2026 for a registration in state 27."""
    return [
        doc("SAL/0001", "sales", "b2b", "27", "1180", [item("1000", cgst="90", sgst="90", qty="10")], gstin=X, name="X Ltd", ptype="regular"),
        doc("SAL/0002", "sales", "b2b", "27", "790",
            [item("500", cgst="45", sgst="45", no=1), item("200", "5", cgst="5", sgst="5", no=2, hsn="2002")],
            gstin=X, name="X Ltd", ptype="regular", day=6),
        doc("SAL/0003", "sales", "b2b", "29", "2360", [item("2000", igst="360")], gstin=Y, name="Y Ltd", ptype="regular", day=7),
        doc("SAL/0004", "sales", "b2c", "29", "354000", [item("300000", igst="54000")], ptype="unregistered", day=8),
        doc("SAL/0005", "sales", "b2c", "27", "118", [item("100", cgst="9", sgst="9")], ptype="unregistered", day=9),
        doc("SAL/0006", "sales", "b2c", "27", "236", [item("200", cgst="18", sgst="18")], ptype="unregistered", day=9),
        doc("SAL/0007", "sales", "export_without_payment", "96", "5000", [item("5000", "0", treatment="zero_rated")],
            gstin=None, name="Foreign Co", day=10),
        doc("SAL/0008", "sales", "b2c", "27", "400", [item("400", "0", treatment="nil_rated", hsn="0401")], ptype="unregistered", day=11),
        doc("CN/0001", "credit_note", "b2b", "27", "118", [item("100", cgst="9", sgst="9")], gstin=X, name="X Ltd", ptype="regular",
            day=20, orig="SAL/0001"),
    ]
