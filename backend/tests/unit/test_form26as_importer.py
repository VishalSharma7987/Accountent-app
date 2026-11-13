"""Package E: 26AS / AIS file reading (T-40). Fixtures are hand-made, not TRACES / AIS files."""

import io
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.importers.form26as import Form26asFileError, parse_26as

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "tds26as" / "form26as_deductee_sample.csv"
HEADER = "Deductor TAN,Name of Deductor,Section,Transaction Date,Amount Paid/Credited,Tax Deducted,Tax Deposited"


def reject(text: str | bytes) -> str:
    with pytest.raises(Form26asFileError) as info:
        parse_26as(text if isinstance(text, bytes) else text.encode())
    return str(info.value)


def test_T40_csv_sample_parses_three_rows_with_literal_values():
    parsed = parse_26as(FIXTURE.read_bytes())
    assert parsed.source_format == "csv" and len(parsed.rows) == 3
    first, second, third = parsed.rows
    assert (first.row_no, first.deductor_tan, first.section_ref, first.transaction_date) == (1, "MUMA12345B", "194C", date(2026, 4, 20))
    assert (first.amount_paid, first.tax_deducted, first.tax_deposited) == (D("100000.00"), D("1000.00"), D("1000.00"))
    assert (second.section_ref, second.amount_paid, second.tax_deducted, second.transaction_date) == ("194J", D("50000.00"), D("5000.00"), date(2026, 5, 10))
    assert third.deductor_name == "Delta Services" and third.booking_status == "F" and third.booking_date == date(2026, 7, 15)


def test_T40_amounts_are_decimals_and_indian_grouping_is_read():
    parsed = parse_26as(f'{HEADER}\nMUMA12345B,X,194C,20-04-2026,"1,00,000.50",1000,1000\n'.encode())
    row = parsed.rows[0]
    assert row.amount_paid == D("100000.50") and isinstance(row.amount_paid, D) and row.tax_deducted == D("1000.00")


def test_T40_three_decimals_rejects_whole_file_naming_the_row():
    message = reject(f"{HEADER}\nMUMA12345B,X,194C,20-04-2026,1000,10.005,10\n")
    assert "row 2" in message and "tax deducted" in message and "decimal" in message.lower()


def test_T40_unknown_column_and_missing_required_column_rejected():
    assert "Unknown column 'Remarks'" in reject(HEADER + ",Remarks\nMUMA12345B,X,194C,20-04-2026,1,1,1,ok\n")
    assert "Required column(s) not found: tax_deposited" in reject("Deductor TAN,Section,Transaction Date,Amount Paid,Tax Deducted\nA,B,C,D,E\n")
    assert "Neither a deductor TAN nor a deductee PAN" in reject("Section,Transaction Date,Amount Paid,Tax Deducted,Tax Deposited\n194C,20-04-2026,1,1,1\n")


def test_T40_bad_tan_pan_date_negative_blank_each_rejected_with_all_rows_listed():
    message = reject(
        f"{HEADER}\nBADTAN,X,194C,20-04-2026,1,1,1\nMUMA12345B,X,194C,31-02-2026,1,1,1\nMUMA12345B,X,194C,20-04-2026,-5,1,1\n"
        "MUMA12345B,X,,20-04-2026,1,1,1\nMUMA12345B,X,194C,20-04-2026,1,,1\n"
    )
    for fragment in ("row 2: deductor TAN 'BADTAN'", "row 3: transaction date '31-02-2026'", "row 4: amount paid: amount -5 is negative",
                     "row 5: section is missing", "row 6: tax deducted is missing"):
        assert fragment in message


def test_T40_pan_format_checked_and_header_only_or_empty_or_pdf_rejected():
    assert "deductee PAN 'ABC'" in reject("Deductee PAN,Section,Transaction Date,Amount Paid,Tax Deducted,Tax Deposited\nABC,194C,20-04-2026,1,1,1\n")
    assert "no data rows" in reject(HEADER + "\n")
    assert reject("") == "The file is empty"
    assert "PDF" in reject(b"%PDF-1.4 ...")


def test_T40_extra_cells_beyond_the_header_rejected():
    assert "more cells than the header" in reject(f"{HEADER}\nMUMA12345B,X,194C,20-04-2026,1,1,1,surprise\n")


def test_T40_excel_first_sheet_read_with_dates_and_float_cells():
    wb = Workbook()
    ws = wb.active
    ws.append(["TAN of Deductor", "Section", "Date of Payment/Credit", "Amount Paid", "Tax Deducted", "Total Tax Deposited"])
    ws.append(["MUMA12345B", "194C", date(2026, 4, 20), 100000.1, 1000.0, 1000])
    buffer = io.BytesIO()
    wb.save(buffer)
    parsed = parse_26as(buffer.getvalue())
    row = parsed.rows[0]
    assert parsed.source_format == "excel" and row.transaction_date == date(2026, 4, 20)
    assert (row.amount_paid, row.tax_deducted, row.tax_deposited) == (D("100000.10"), D("1000.00"), D("1000.00"))


def test_T40_broken_workbook_rejected():
    assert "not a readable .xlsx" in reject(b"PK\x03\x04garbage")
