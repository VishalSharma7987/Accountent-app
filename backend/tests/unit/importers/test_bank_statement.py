"""Bank statement parser (pure): rows -> lines with the row number on every problem; R-01 integrity."""

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.importers.bank_statement import MappingError, parse_statement, validate_mapping

D = Decimal

SPLIT = {
    "header_row": 1, "date_col": "Date", "date_format": "%d/%m/%Y", "description_col": "Narration",
    "reference_col": "Chq/Ref No", "debit_col": "Withdrawal", "credit_col": "Deposit", "balance_col": "Balance",
}
SINGLE = {
    "header_row": 1, "date_col": "Txn Date", "date_format": "%d-%b-%y", "description_col": "Particulars",
    "amount_col": "Amount", "drcr_col": "Dr/Cr",
}
NO_BAL = {k: v for k, v in SPLIT.items() if k not in ("reference_col", "balance_col")}


def csv_bytes(text, encoding="utf-8"):
    return text.encode(encoding)


def make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


GOOD_CSV = (
    "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
    "05/04/2026,Rent paid,000123,10000.00,,90000.00\n"
    "06/04/2026,Sale receipt,UTR998,,5000.50,95000.50\n"
)


def test_R01_split_columns_parsed_with_opening_argument():
    p = parse_statement(csv_bytes(GOOD_CSV), SPLIT, opening_balance="100000.00")
    assert p.problems == []
    assert [(x.row, x.txn_date, x.description, x.reference, x.debit, x.credit, x.balance) for x in p.lines] == [
        (2, date(2026, 4, 5), "Rent paid", "000123", D("10000.00"), D("0.00"), D("90000.00")),
        (3, date(2026, 4, 6), "Sale receipt", "UTR998", D("0.00"), D("5000.50"), D("95000.50")),
    ]
    assert (p.period_from, p.period_to) == (date(2026, 4, 5), date(2026, 4, 6))
    assert (p.opening_balance, p.closing_balance) == (D("100000.00"), D("95000.50"))


def test_R01_opening_balance_from_mapping_value_and_cell():
    m = {**SPLIT, "opening_balance": "100000"}
    assert parse_statement(csv_bytes(GOOD_CSV), m).opening_balance == D("100000.00")
    csv = "Opening,100000.00\n" + GOOD_CSV
    m2 = {**SPLIT, "header_row": 2, "opening_balance_cell": "B1"}
    p = parse_statement(csv_bytes(csv), m2)
    assert p.problems == [] and p.opening_balance == D("100000.00")


def test_R01_opening_missing_is_a_problem_not_a_guess():
    p = parse_statement(csv_bytes(GOOD_CSV), SPLIT)
    assert p.opening_balance is None
    assert [x.row for x in p.problems] == [0]
    assert "opening balance" in p.problems[0].message


def test_R01_running_balance_mismatch_names_first_row_with_indian_amounts():
    bad = GOOD_CSV.replace("95000.50", "9500000.50")
    p = parse_statement(csv_bytes(bad), SPLIT, opening_balance="100000.00")
    assert len(p.problems) == 1
    assert p.problems[0].row == 3
    assert p.problems[0].message == (
        "Row 3: running balance 95,00,000.50 does not agree with the previous balance 90,000.00 + credit 5,000.50 "
        "- debit 0.00 = 95,000.50"
    )


def test_R01_first_row_checked_against_opening():
    p = parse_statement(csv_bytes(GOOD_CSV), SPLIT, opening_balance="99999.00")
    assert p.problems[0].row == 2
    assert p.problems[0].message.endswith("= 89,999.00")


def test_R01_without_balance_column_closing_argument_must_tie():
    csv = "Date,Narration,Withdrawal,Deposit\n05/04/2026,Rent,10000.00,\n06/04/2026,Sale,,5000.50\n"
    ok = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="100000", closing_balance="95000.50")
    assert ok.problems == [] and ok.closing_balance == D("95000.50")
    bad = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="100000", closing_balance="95000.00")
    assert bad.problems[0].message == (
        "Opening 1,00,000.00 + credits 5,000.50 - debits 10,000.00 = 95,000.50, but the closing balance is 95,000.00"
    )
    missing = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="100000")
    assert missing.closing_balance is None and "closing balance" in missing.problems[0].message


def test_V03_amount_comma_thousands_in_text_cells():
    csv = (
        "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
        '05/04/2026,Big,1,"1,00,000.00",,"4,00,000.00"\n'
        '06/04/2026,Back,2,,"2,500.25","4,02,500.25"\n'
    )
    p = parse_statement(csv_bytes(csv), SPLIT, opening_balance="500000")
    assert p.problems == []
    assert [(x.debit, x.credit) for x in p.lines] == [(D("100000.00"), D("0.00")), (D("0.00"), D("2500.25"))]


def test_V03_more_than_two_decimals_and_negative_are_problems_with_row():
    csv = "Date,Narration,Withdrawal,Deposit\n05/04/2026,A,10.005,\n06/04/2026,B,-5.00,\n"
    p = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="0", closing_balance="0")
    assert [x.row for x in p.problems] == [2, 3]
    assert "more than 2 decimal places" in p.problems[0].message
    assert "negative" in p.problems[1].message


def test_V02_row_with_both_debit_and_credit_is_a_problem():
    csv = "Date,Narration,Withdrawal,Deposit\n05/04/2026,A,10.00,5.00\n"
    p = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="0", closing_balance="0")
    assert p.problems[0].row == 2
    assert p.problems[0].message == "Row 2: both a debit (10.00) and a credit (5.00) are filled; a row has only one side"


def test_row_with_date_but_no_amount_is_a_problem_not_skipped():
    csv = "Date,Narration,Withdrawal,Deposit\n05/04/2026,A,,\n"
    p = parse_statement(csv_bytes(csv), NO_BAL, opening_balance="0", closing_balance="0")
    assert p.problems[0].row == 2 and "no debit or credit amount" in p.problems[0].message


def test_bad_date_is_a_problem_with_row_and_format():
    csv = GOOD_CSV.replace("06/04/2026", "2026-04-06")
    p = parse_statement(csv_bytes(csv), SPLIT, opening_balance="100000.00")
    assert p.problems[0].row == 3
    assert p.problems[0].message == "Row 3: date '2026-04-06' does not match the format %d/%m/%Y"


def test_footer_and_blank_rows_without_a_date_are_skipped():
    csv = GOOD_CSV + "\n,,,,,\nTotal,,,10000.00,5000.50,\nGenerated on 07/04/2026\n"
    p = parse_statement(csv_bytes(csv), SPLIT, opening_balance="100000.00")
    assert p.problems == [] and len(p.lines) == 2


def test_utf8_sig_and_semicolon_and_tab_delimiters():
    p = parse_statement(csv_bytes(GOOD_CSV, "utf-8-sig"), SPLIT, opening_balance="100000.00")
    assert p.problems == [] and len(p.lines) == 2
    semi = GOOD_CSV.replace(",", ";")
    assert len(parse_statement(csv_bytes(semi), SPLIT, opening_balance="100000.00").lines) == 2
    tab = GOOD_CSV.replace(",", "\t")
    assert len(parse_statement(csv_bytes(tab), SPLIT, opening_balance="100000.00").lines) == 2


def test_single_amount_with_drcr_column_and_dd_mon_yy_dates():
    csv = (
        "Txn Date,Particulars,Amount,Dr/Cr\n"
        '05-Apr-26,Rent,"10,000.00",DR\n'
        "06-Apr-26,Sale,5000.50,Cr\n"
        "07-Apr-26,Fee,11.00,D\n"
        "08-Apr-26,Int,1.00,c\n"
    )
    p = parse_statement(csv_bytes(csv), SINGLE, opening_balance="100000", closing_balance="94990.50")
    assert p.problems == []
    assert [(x.txn_date, x.debit, x.credit) for x in p.lines] == [
        (date(2026, 4, 5), D("10000.00"), D("0.00")),
        (date(2026, 4, 6), D("0.00"), D("5000.50")),
        (date(2026, 4, 7), D("11.00"), D("0.00")),
        (date(2026, 4, 8), D("0.00"), D("1.00")),
    ]


def test_drcr_unknown_value_is_a_problem():
    csv = "Txn Date,Particulars,Amount,Dr/Cr\n05-Apr-26,Rent,10.00,X\n"
    p = parse_statement(csv_bytes(csv), SINGLE, opening_balance="0", closing_balance="0")
    assert p.problems[0].row == 2 and "Dr/Cr" in p.problems[0].message


def test_xlsx_with_real_dates_numbers_and_header_on_row_3():
    rows = [
        ["Account statement"], [],
        ["Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"],
        [date(2026, 4, 5), "Rent", 123456.0, 10000, None, 90000],
        [date(2026, 4, 6), "Sale", "UTR1", None, 5000.5, 95000.5],
        [None, "Total", None, 10000, 5000.5, None],
    ]
    p = parse_statement(make_xlsx(rows), {**SPLIT, "header_row": 3}, opening_balance="100000")
    assert p.problems == []
    assert [(x.row, x.reference, x.debit, x.credit, x.balance) for x in p.lines] == [
        (4, "123456", D("10000.00"), D("0.00"), D("90000.00")),
        (5, "UTR1", D("0.00"), D("5000.50"), D("95000.50")),
    ]


def test_xlsx_float_that_is_not_two_decimals_is_rejected():
    rows = [["Date", "Narration", "Withdrawal", "Deposit"], [date(2026, 4, 5), "x", 10.005, None]]
    p = parse_statement(make_xlsx(rows), NO_BAL, opening_balance="0", closing_balance="0")
    assert p.problems[0].row == 2 and "more than 2 decimal places" in p.problems[0].message


def test_missing_column_and_empty_file_are_file_level_problems():
    p = parse_statement(csv_bytes("Date,Narration\n05/04/2026,x\n"), SPLIT, opening_balance="0")
    assert p.problems[0].row == 1 and any("'Withdrawal'" in x.message for x in p.problems)
    empty = parse_statement(
        csv_bytes("Date,Narration,Withdrawal,Deposit\n"), NO_BAL, opening_balance="0", closing_balance="0"
    )
    assert "no transactions" in empty.problems[0].message


def test_column_names_match_case_insensitively():
    csv = GOOD_CSV.replace("Narration", "NARRATION  ")
    assert parse_statement(csv_bytes(csv), SPLIT, opening_balance="100000.00").problems == []


def test_validate_mapping_shapes():
    assert validate_mapping(SPLIT)["debit_col"] == "Withdrawal"
    assert validate_mapping(SINGLE)["amount_col"] == "Amount"
    for bad in (
        {**SPLIT, "header_row": 0},
        {**SPLIT, "date_format": "not a format"},
        {k: v for k, v in SPLIT.items() if k != "credit_col"},
        {**SPLIT, "amount_col": "Amount", "drcr_col": "Dr/Cr"},
        {**SPLIT, "surprise": "x"},
        {**SPLIT, "opening_balance": "1", "opening_balance_cell": "B1"},
        {**SPLIT, "opening_balance_cell": "banana"},
        {**SPLIT, "opening_balance": "1.234"},
    ):
        with pytest.raises(MappingError):
            validate_mapping(bad)


def test_not_a_spreadsheet_is_a_file_level_problem():
    p = parse_statement(b"PK\x03\x04garbage", SPLIT, opening_balance="0")
    assert p.problems and p.problems[0].row == 0
