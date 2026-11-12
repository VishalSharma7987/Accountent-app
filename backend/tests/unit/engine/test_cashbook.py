"""Cash Book / Bank Book (step 2.4): daily receipts, payments and closing balance, by hand."""

from datetime import date
from decimal import Decimal

import pytest

from app.engine.cashbook import cash_book
from app.engine.models import Balance, Ledger, OpeningBalance, PostedLine

D = Decimal
CASH = Ledger("cash", "Cash", "cash_in_hand", True, "c1")


def pl(vid, number, vtype, on, status, line_no, ledger_id, name, dr="0", cr="0", narration="n"):
    return PostedLine(vid, number, vtype, on, narration, status, line_no, ledger_id, name, D(dr), D(cr))


LINES = [
    pl("v0", "REC/1", "receipt", date(2026, 4, 2), "posted", 1, "cash", "Cash", dr="5000"),
    pl("v0", "REC/1", "receipt", date(2026, 4, 2), "posted", 2, "sales", "Sales", cr="5000"),
    pl("v1", "REC/2", "receipt", date(2026, 4, 3), "posted", 1, "cash", "Cash", dr="10000"),
    pl("v1", "REC/2", "receipt", date(2026, 4, 3), "posted", 2, "rahul", "Rahul Enterprises", cr="10000"),
    pl("v2", "PAY/1", "payment", date(2026, 4, 3), "posted", 1, "rent", "Rent", dr="3000.50"),
    pl("v2", "PAY/1", "payment", date(2026, 4, 3), "posted", 2, "cash", "Cash", cr="3000.50"),
    # reversed original and its reversal both count
    pl("v3", "PAY/2", "payment", date(2026, 4, 5), "reversed", 1, "freight", "Freight Inward", dr="1000"),
    pl("v3", "PAY/2", "payment", date(2026, 4, 5), "reversed", 2, "rent", "Rent", dr="500"),
    pl("v3", "PAY/2", "payment", date(2026, 4, 5), "reversed", 3, "cash", "Cash", cr="1500"),
    pl("v4", "PAY/3", "payment", date(2026, 4, 6), "posted", 1, "freight", "Freight Inward", cr="1000"),
    pl("v4", "PAY/3", "payment", date(2026, 4, 6), "posted", 2, "rent", "Rent", cr="500"),
    pl("v4", "PAY/3", "payment", date(2026, 4, 6), "posted", 3, "cash", "Cash", dr="1500"),
    # a draft never counts
    pl("v5", None, "payment", date(2026, 4, 7), "draft", 1, "rent", "Rent", dr="99999"),
    pl("v5", None, "payment", date(2026, 4, 7), "draft", 2, "cash", "Cash", cr="99999"),
]
OPENING = OpeningBalance(D("50000.00"), D("0.00"))


def test_cashbook_opening_folds_earlier_entries():
    book = cash_book(CASH, OPENING, LINES, date(2026, 4, 3), date(2026, 4, 10))
    assert book.opening == Balance(D("55000.00"), "Dr")


def test_cashbook_days_receipts_payments_closing():
    book = cash_book(CASH, OPENING, LINES, date(2026, 4, 3), date(2026, 4, 10))
    assert [d.date for d in book.days] == [date(2026, 4, 3), date(2026, 4, 5), date(2026, 4, 6)]
    d3, d5, d6 = book.days
    assert (d3.receipts, d3.payments, d3.closing) == (D("10000.00"), D("3000.50"), Balance(D("61999.50"), "Dr"))
    assert (d5.receipts, d5.payments, d5.closing) == (D("0.00"), D("1500.00"), Balance(D("60499.50"), "Dr"))
    assert (d6.receipts, d6.payments, d6.closing) == (D("1500.00"), D("0.00"), Balance(D("61999.50"), "Dr"))


def test_cashbook_totals_and_closing():
    book = cash_book(CASH, OPENING, LINES, date(2026, 4, 3), date(2026, 4, 10))
    assert book.total_receipts == D("11500.00")
    assert book.total_payments == D("4500.50")
    assert book.closing == Balance(D("61999.50"), "Dr")


def test_cashbook_entries_name_counter_ledgers():
    book = cash_book(CASH, OPENING, LINES, date(2026, 4, 3), date(2026, 4, 10))
    d3, d5, _ = book.days
    assert [(e.voucher_number, e.counter_ledgers, e.receipt, e.payment) for e in d3.entries] == [
        ("REC/2", ("Rahul Enterprises",), D("10000.00"), D("0.00")),
        ("PAY/1", ("Rent",), D("0.00"), D("3000.50")),
    ]
    assert d5.entries[0].counter_ledgers == ("Freight Inward", "Rent")
    assert d5.entries[0].voucher_type == "payment"


def test_cashbook_credit_balance_and_empty_range():
    book = cash_book(CASH, OpeningBalance(D("0.00"), D("100.00")), [], date(2026, 4, 1), date(2026, 4, 30))
    assert book.opening == Balance(D("100.00"), "Cr") and book.days == ()
    assert book.closing == Balance(D("100.00"), "Cr")


def test_cashbook_rejects_reversed_range():
    with pytest.raises(ValueError):
        cash_book(CASH, OPENING, LINES, date(2026, 4, 10), date(2026, 4, 3))
