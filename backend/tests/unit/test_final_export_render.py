"""Package E: Excel / PDF rendering (F-70) and the export block (F-71). No database: documents are built by hand."""

import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.services import final_export
from app.services.errors import ServiceError
from app.services.final_export_render import render, to_pdf, to_xlsx

LEDGER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ID = "22222222-2222-2222-2222-222222222222"


def line(code, label, amount, drill=(), **kw):
    return {"code": code, "label": label, "amount": amount, "previous_amount": None, "note_no": None, "level": 0, "is_total": False,
            "drill": list(drill), **kw}


def drill(ledger_id, name, amount):
    return {"ledger_id": ledger_id, "ledger_name": name, "amount": amount}


def doc():
    trading = {"key": "trading", "format": "horizontal", "title": "Trading Account", "from_date": "2026-04-01", "to_date": "2027-03-31",
               "left": [line("opening_stock", "Opening stock", "200000.00", [drill(LEDGER_ID, "Stock", "200000.00")]),
                        line("gross_profit", "Gross profit c/d", "420000.00"), line("total", "Total", "1450000.00", is_total=True)],
               "right": [line("sales", "Sales", "1200000.00", [drill(OTHER_ID, "Sales A", "700000.00"), drill(LEDGER_ID, "Stock", "500000.00")]),
                         line("total", "Total", "1450000.00", is_total=True)],
               "totals": {"gross_profit": "420000.00"}, "notes": [], "findings": [], "engine_version": "fin-1", "rule_status": []}
    cash = {"key": "cash_flow", "format": "vertical", "title": "Cash Flow Statement", "from_date": "2026-04-01", "to_date": "2027-03-31",
            "left": [line("heading:a", "A. Operating", "0.00"), line("x", "Increase in stock", "-50000.00", level=1),
                     line("net_increase", "Net increase", "55000.00", is_total=True)],
            "right": [], "totals": {"net_increase": "55000.00"}, "notes": [], "findings": [], "engine_version": "fin-1", "rule_status": []}
    sections = [{"name": "Trading", "title": "Trading Account", "statement": trading, "warnings": ["Warning F-44: sample"],
                 "header": [("Law rule status", "2 rule row(s): 2 pending. PENDING: not verified")]},
                {"name": "Cash Flow", "title": "Cash Flow Statement", "statement": cash, "warnings": [], "header": []}]
    return {"title": "Final statements", "client": "Test Traders", "fy_label": "01-04-2026 to 31-03-2027", "engine_version": "fin-1",
            "header": [("Basis", "horizontal; closing stock manual")], "sections": sections, "status_line": "rules: pending",
            "ledgers": [{"ledger_id": LEDGER_ID, "name": "Stock", "group_code": "stock_in_hand", "opening": "200000.00",
                         "debit_total": "0.00", "credit_total": "0.00", "closing": "200000.00"},
                        {"ledger_id": OTHER_ID, "name": "Sales A", "group_code": "sales_accounts", "opening": "0.00",
                         "debit_total": "0.00", "credit_total": "700000.00", "closing": "-700000.00"}]}


def test_F70_excel_sheets_header_and_numbers():
    wb = load_workbook(io.BytesIO(to_xlsx(doc())))
    assert wb.sheetnames == ["Trading", "Cash Flow", "Ledgers"]
    ws = wb["Trading"]
    text = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "Test Traders" in text and "01-04-2026 to 31-03-2027" in text and "fin-1" in text
    assert any("PENDING" in t for t in text)
    assert "Warning F-44: sample" in text
    assert Decimal("200000.00") in [c.value for row in ws.iter_rows() for c in row]
    cf = wb["Cash Flow"]
    assert Decimal("-50000.00") in [c.value for row in cf.iter_rows() for c in row]


def test_F70_excel_ledger_hyperlinks_point_to_ledgers_sheet():
    wb = load_workbook(io.BytesIO(to_xlsx(doc())))
    links = {c.value: c.hyperlink.location for row in wb["Trading"].iter_rows() for c in row if c.hyperlink}
    assert links["Stock"] == "'Ledgers'!A8"
    assert links["Sales A"] == "'Ledgers'!A9"
    ledgers = wb["Ledgers"]
    assert ledgers["B8"].value == "Stock" and ledgers["D8"].value == "2,00,000.00 Dr"
    assert ledgers["B9"].value == "Sales A" and ledgers["G9"].value == "7,00,000.00 Cr"
    refs = [c.value for row in wb["Trading"].iter_rows() for c in row if c.value in ("L001", "L002, L001")]
    assert refs == ["L001", "L002, L001"]


def test_F70_pdf_is_a_pdf_with_pages():
    data = to_pdf(doc())
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 2   # one page per statement
    assert render(doc(), "pdf")[1] == "application/pdf"


def test_F71_error_finding_blocks_export():
    findings = [{"statement": "Trading Account", "rule_id": "F-41", "message": "Closing stock is not approved", "severity": "error"}]
    with pytest.raises(ServiceError) as caught:
        final_export._block(findings)
    assert caught.value.code == "export_blocked"
    assert "F-71" in caught.value.message
    final_export._block([])                        # no error, no exception


def test_F71_only_errors_are_collected_warnings_are_printed():
    mixed = [{"rule_id": "F-44", "message": "w", "severity": "warning"}, {"rule_id": "F-40", "message": "e", "severity": "error"}]
    assert [e["rule_id"] for e in final_export._errors("T", mixed)] == ["F-40"]
    assert final_export._warnings(mixed) == ["Warning F-44: w"]


def test_F70_rule_text_says_pending():
    assert final_export._rule_text([{"verification_status": "pending"}, {"verification_status": "pending"}]).startswith("2 rule row(s): 2 pending")
    assert "PENDING" in final_export._rule_text([{"verification_status": "pending"}])
    assert "PENDING" not in final_export._rule_text([{"verification_status": "verified"}])


def test_F70_statement_selection_defaults_and_validation():
    assert final_export.parse_statements(None, True, False) == ["balance_sheet", "profit_loss", "cash_flow"]
    assert final_export.parse_statements(None, False, True) == ["trading", "profit_loss", "appropriation", "balance_sheet"]
    assert final_export.parse_statements("cash_flow,trading", False, False) == ["trading", "cash_flow"]
    with pytest.raises(ServiceError):
        final_export.parse_statements("nonsense", False, False)
