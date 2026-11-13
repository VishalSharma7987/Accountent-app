"""TDS exports carry exactly the figures of the working (round trip from the file). Literal expected values (T-50, T-31)."""

import io
import json
from datetime import date
from decimal import Decimal as D

from openpyxl import load_workbook

from app.services import tds_export
from app.services.tds_returns import jsonable

STATUS = {"worst": "pending", "tables": {"form": "secondary_verified", "rate": "pending"}, "pending_sources": ["194C rate source"]}


def working():
    return jsonable({
        "return_kind": "non_salary_resident", "form_no": "Form 140", "form_status": "secondary_verified", "tan": "DELA12345B",
        "financial_year": "2026-27", "quarter": 1, "period_start": date(2026, 4, 1), "period_end": date(2026, 6, 30), "version": 2,
        "status": "draft",
        "deductee_rows": [{"deductee_name": "Alpha Contractors", "pan": "AAAPA1111A", "section_ref": "194C", "amount_paid": D("100000.00"),
                           "tax_deducted": D("1000.00"), "tax_deposited": D("1000.00"), "rate": D("1.0000"), "error_row": False,
                           "event_date": date(2026, 5, 10)}],
        "challan_rows": [{"bsr_code": "0510308", "serial_no": "00041", "tax": D("1000.00"), "interest": D("0.00"), "fee": D("0.00"),
                          "total": D("1000.00"), "deposit_date": date(2026, 6, 7)}],
        "totals": {"amount_paid": D("100000.00"), "tax_deducted": D("1000.00"), "tax_deposited": D("1000.00"), "row_count": 1},
        "errors": [], "warnings": [{"rule_id": "T-50", "message": "Payment codes are missing"}], "rule_status": STATUS,
    })


def test_T50_excel_summary_lists_form_status_pending_sources_and_warnings():
    wb = load_workbook(io.BytesIO(tds_export.working_to_xlsx(working())))
    summary = [list(r) for r in wb["Summary"].iter_rows(values_only=True)]
    assert ["Form (from rule table)", "Form 140"] in summary
    assert ["Worst rule status", "pending"] in summary
    assert ["PENDING rule, to be verified", "194C rate source"] in summary
    assert ["Warning", "T-50: Payment codes are missing"] in summary
    assert ["File format", "unverified-own-structure (not the official statement file)"] in summary


def test_T31_excel_rows_are_numbers_equal_to_the_working_and_pan_stays_text():
    wb = load_workbook(io.BytesIO(tds_export.working_to_xlsx(working())))
    rows = list(wb["Deductee rows"].iter_rows(values_only=True))
    head, row = rows[0], rows[1]
    got = dict(zip(head, row, strict=True))
    assert got["amount_paid"] == 100000 and got["tax_deducted"] == 1000 and got["rate"] == 1
    assert got["pan"] == "AAAPA1111A" and got["error_row"] == "No"
    ch = dict(zip(*[list(r) for r in wb["Challans"].iter_rows(values_only=True)][:2], strict=True))
    assert ch["bsr_code"] == "0510308" and ch["serial_no"] == "00041" and ch["total"] == 1000


def test_T50_json_is_labelled_unverified_and_keeps_exact_amount_strings():
    out = tds_export.working_json(working())
    assert out["format_status"] == "unverified-own-structure"
    assert out["form_no"] == "Form 140"
    assert out["totals"]["tax_deducted"] == "1000.00"
    assert out["deductee_rows"][0]["amount_paid"] == "100000.00"
    assert json.loads(tds_export.dumps(out))["rule_status"]["worst"] == "pending"


def test_T34_certificate_excel_has_header_totals_and_tables():
    cert = {
        "form_no": "Form 131", "form_status": "secondary_verified", "period": "FY 2026-27 Q1", "version": 1, "certificate_no": None,
        "issued_on": None, "deductor": {"name": "Acme", "tan": "DELA12345B", "pan": "AAACA1234A"},
        "deductee": {"name": "Alpha", "pan": "AAAPA1111A"}, "rule_status": STATUS,
        "items": [{"voucher_number": "PAY/1", "section_ref": "194C", "amount_paid": "100000.00", "rate": "1", "tax_deducted": "1000.00",
                   "tax_deposited": "1000.00"}],
        "challans": [{"bsr_code": "0510308", "serial_no": "00041", "tax_deposited": "1000.00"}],
        "total_amount_paid": "100000.00", "total_deducted": "1000.00", "total_deposited": "1000.00",
    }
    wb = load_workbook(io.BytesIO(tds_export.certificate_to_xlsx(cert)))
    summary = [list(r) for r in wb["Summary"].iter_rows(values_only=True)]
    assert ["Deductor TAN", "DELA12345B"] in summary
    assert ["Total: total_deducted", 1000] in summary
    items = [list(r) for r in wb["Items"].iter_rows(values_only=True)]
    assert items[1][items[0].index("tax_deposited")] == 1000
