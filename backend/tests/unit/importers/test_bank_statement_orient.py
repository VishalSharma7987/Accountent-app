"""Bank statement parser: newest-first files (detected only from the running balances) and Cr/Dr balance text.
All expected values are hand-calculated."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.money import MoneyError
from app.importers.bank_statement import (
    MappingError,
    parse_balance_text,
    parse_statement,
    validate_mapping,
)

D = Decimal

SPLIT = {
    "header_row": 1, "date_col": "Date", "date_format": "%d/%m/%Y", "description_col": "Narration",
    "reference_col": "Chq/Ref No", "debit_col": "Withdrawal", "credit_col": "Deposit", "balance_col": "Balance",
}
NO_BAL = {k: v for k, v in SPLIT.items() if k not in ("reference_col", "balance_col")}
HEAD = "Date,Narration,Chq/Ref No,Withdrawal,Deposit,Balance\n"
NOTE = "file was newest-first; rows reversed"


def parse(text, mapping=SPLIT, **kw):
    return parse_statement(text.encode(), mapping, **kw)


# opening 1,000.00: +500 -> 1,500.00 ; -200 -> 1,300.00 ; +50 -> 1,350.00
NEWEST_FIRST = (
    HEAD
    + "03/04/2026,Third,,,50.00,1350.00\n"
    + "02/04/2026,Second,,200.00,,1300.00\n"
    + "01/04/2026,First,,,500.00,1500.00\n"
)


def test_R01_newest_first_file_with_balances_is_reversed_and_noted():
    p = parse(NEWEST_FIRST, opening_balance="1000.00")
    assert p.problems == []
    assert [x.description for x in p.lines] == ["First", "Second", "Third"]
    assert [x.row for x in p.lines] == [4, 3, 2]
    assert (p.opening_balance, p.closing_balance) == (D("1000.00"), D("1350.00"))
    assert (p.period_from, p.period_to) == (date(2026, 4, 1), date(2026, 4, 3))
    assert p.notes == [NOTE]


def test_R01_oldest_first_file_is_not_reversed_and_has_no_notes():
    p = parse(HEAD + "01/04/2026,First,,,500.00,1500.00\n02/04/2026,Second,,200.00,,1300.00\n", opening_balance="1000")
    assert p.problems == [] and p.notes == []
    assert [x.description for x in p.lines] == ["First", "Second"]


def test_R01_newest_first_closing_argument_is_checked_against_the_newest_row():
    ok = parse(NEWEST_FIRST, opening_balance="1000.00", closing_balance="1350.00")
    assert ok.problems == [] and ok.closing_balance == D("1350.00")
    bad = parse(NEWEST_FIRST, opening_balance="1000.00", closing_balance="1500.00")
    assert "closing balance" in bad.problems[0].message


def test_R01_neither_order_validates_reports_first_row_of_file_order():
    p = parse(NEWEST_FIRST.replace("1300.00", "1301.00"), opening_balance="1000.00")
    assert p.notes == []
    # file order: opening 1,000.00 + credit 50.00 = 1,050.00, but the first data row prints 1,350.00
    assert [x.row for x in p.problems] == [2]
    assert "1,350.00" in p.problems[0].message and "1,050.00" in p.problems[0].message


def test_R01_newest_first_needs_the_opening_balance_no_guess():
    p = parse(NEWEST_FIRST)
    assert [x.row for x in p.problems] == [0] and "opening balance" in p.problems[0].message
    assert p.notes == []


def test_R01_newest_first_without_balance_column_is_rejected_not_reversed():
    newest = "Date,Narration,Withdrawal,Deposit\n03/04/2026,Third,,50.00\n02/04/2026,Second,200.00,\n01/04/2026,First,,500.00\n"
    p = parse(newest, NO_BAL, opening_balance="1000.00", closing_balance="1350.00")
    assert [x.row for x in p.problems] == [0]
    assert "oldest-first" in p.problems[0].message and "balance column" in p.problems[0].message
    oldest = "Date,Narration,Withdrawal,Deposit\n01/04/2026,First,,500.00\n02/04/2026,Second,200.00,\n03/04/2026,Third,,50.00\n"
    assert parse(oldest, NO_BAL, opening_balance="1000.00", closing_balance="1350.00").problems == []


def test_R01_without_balance_column_same_day_rows_are_not_a_newest_first_file():
    same_day = "Date,Narration,Withdrawal,Deposit\n01/04/2026,A,,500.00\n01/04/2026,B,200.00,\n"
    assert parse(same_day, NO_BAL, opening_balance="1000", closing_balance="1300").problems == []


def test_R01_newest_first_days_with_oldest_first_rows_inside_a_day():
    # opening 1,000: day 2 file order [+500 bal 1,500 ; -200 bal 1,300], day 3 +50 bal 1,350. Full reversal would
    # start with -200 (1,000 - 200 = 800 != 1,300); only the day groups reversed agree with every balance.
    csv = (
        HEAD
        + "03/04/2026,Third,,,50.00,1350.00\n"
        + "02/04/2026,Second A,,,500.00,1500.00\n"
        + "02/04/2026,Second B,,200.00,,1300.00\n"
    )
    p = parse(csv, opening_balance="1000.00")
    assert p.problems == []
    assert [x.description for x in p.lines] == ["Second A", "Second B", "Third"]
    assert p.notes == [NOTE]


def test_R01_newest_first_days_and_rows_both_newest_first_within_a_day():
    # opening 1,000: day 1 +500 -> 1,500 ; day 2: -200 -> 1,300 then +50 -> 1,350 ; file shows day 2 newest row first
    csv = (
        HEAD
        + "02/04/2026,Second B,,,50.00,1350.00\n"
        + "02/04/2026,Second A,,200.00,,1300.00\n"
        + "01/04/2026,First,,,500.00,1500.00\n"
    )
    p = parse(csv, opening_balance="1000.00")
    assert p.problems == []
    assert [x.description for x in p.lines] == ["First", "Second A", "Second B"]


# ---------------------------------------------------------------------------- Cr / Dr balance text


@pytest.mark.parametrize("text,expected", [
    ("1,234.00 Cr", D("1234.00")), ("Cr 1,234.00", D("1234.00")), ("1234.00Dr", D("-1234.00")),
    ("DR 500", D("-500.00")), ("cr 7.5", D("7.50")), ("  12,00,000.50 cr ", D("1200000.50")),
    ("500 dr", D("-500.00")), ("Dr. 10", D("-10.00")), ("0.00 Dr", D("0.00")), ("1234.50", D("1234.50")),
    ("-1234.50", D("-1234.50")), ("CR1,000", D("1000.00")),
])
def test_R01_balance_text_cr_dr_forms(text, expected):
    assert parse_balance_text(text) == expected


@pytest.mark.parametrize("text", ["abc Cr", "Cr", "-100 Cr", "Cr 100 Dr", "100 Xr", "1.005 Cr", "Dr -5", "1 000 Cr", "Cr Dr"])
def test_R01_balance_text_ambiguous_or_bad_is_rejected(text):
    with pytest.raises(MoneyError):
        parse_balance_text(text)


def test_R01_balance_column_with_cr_dr_and_opening_closing_arguments():
    # Cr = money in the account (+), Dr = overdrawn (-). opening 1,000 Cr; +500 -> 1,500 Cr; -2,000 -> 500 Dr
    csv = HEAD + '01/04/2026,A,,,500.00,"1,500.00 Cr"\n02/04/2026,B,,2000.00,,500.00 Dr\n'
    p = parse(csv, opening_balance="1000.00 Cr", closing_balance="Dr 500")
    assert p.problems == []
    assert [x.balance for x in p.lines] == [D("1500.00"), D("-500.00")]
    assert (p.opening_balance, p.closing_balance) == (D("1000.00"), D("-500.00"))


def test_R01_mapping_opening_balance_accepts_cr_dr():
    assert validate_mapping({**SPLIT, "opening_balance": "250.00 Dr"})["opening_balance"] == "-250.00"
    assert validate_mapping({**SPLIT, "opening_balance": "Cr 250"})["opening_balance"] == "250.00"
    with pytest.raises(MappingError):
        validate_mapping({**SPLIT, "opening_balance": "1000 Cr Dr"})


def test_R01_opening_balance_cell_with_dr_suffix():
    csv = 'Opening,"2,000.00 Dr"\n' + HEAD + "01/04/2026,A,,,500.00,1500.00 Dr\n"
    p = parse(csv, {**SPLIT, "header_row": 2, "opening_balance_cell": "B1"})
    assert p.problems == [] and p.opening_balance == D("-2000.00") and p.closing_balance == D("-1500.00")


def test_R01_unreadable_balance_cell_text_is_a_row_problem():
    p = parse(HEAD + "01/04/2026,A,,,500.00,1500.00 Cr Dr\n", opening_balance="1000")
    assert [x.row for x in p.problems] == [2] and "balance" in p.problems[0].message
